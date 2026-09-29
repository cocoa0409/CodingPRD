# Worklog — task_2908_wholesale_auction_arbitration_condition_disputes

## Step 1: Create task directory — 2026-09-05T15:08:41.885Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes` and its `workspace/` subdirectory. Index 2908 was pre-assigned by the invoker (no scan of ./tasks/, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-05T16:36:12.476Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter is clean on the first run.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/`)
- `SCAFFOLD.yaml` — 3144 lines (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2055 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3672 lines (single top-level key `scaffold_corner_design`)

All three parse with `yaml.safe_load`.

**SCAFFOLD.yaml counts**: 14 entities, 6 state machines, 2 concurrency (OCC) rules, 9 calculations, 48 validation rules, 42 endpoints, 43 error ids, 6 roles (AuctionAdmin, BlockClerk, Arbitrator, Inspector, BuyerRep, SellerRep).

**§1.8 difficulty design**: 9 rules (all nine of §0.5), 23 instances.

**§1.9 corner design**: 9 sections, 110 instances — 73 live `test_recipe` instances and 37 `excluded_because` stubs that cite a §1.8 instance by name. Per section: entities 12, state_machines 25, calculations 15, validations 22, endpoints 5, errors 15, rbac 9, complexity_layers 6, consistency_model 1. Instance names are unique across the union of both design files; all 43 error ids are triggerable across §1.8 ∪ §1.9.

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2908_wholesale_auction_arbitration_condition_disputes/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2908_wholesale_auction_arbitration_condition_disputes/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2908_wholesale_auction_arbitration_condition_disputes/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    42
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  785

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Flag for the orchestrator**: the scenario was used verbatim as instructed, so `scenario:` in SCAFFOLD.yaml still begins with the literal line `Generate task harder than expert level!`. Per the known leak path (scaffold `scenario` → PRD.md), strip that line after Step 2 if you don't want the difficulty directive reaching the PRD. Nothing outside the task directory was created or modified, and `worklog.md` / `workspace/` were left untouched (no scratch files were needed).

Orchestrator note: acted on that flag — removed the `Generate task harder than expert level!` line (and its blank line) from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. `grep -rn "harder than expert" SCAFFOLD*.yaml` now returns nothing and SCAFFOLD.yaml still parses (3142 lines after the 2-line strip).

## Step 3: Copy shared files — 2026-09-05T16:36:12.476Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-05T16:55:08.234Z

Subagent summary (verbatim):

PRD.md is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/workspace/PRD.md` — **502 lines**, written as one small `Write` (header + §1 + §2.1) plus a `cat` of the canonical §2.2 file plus seven heredoc `cat >>` appends. No truncation.

**Section list**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Record Identity, Timestamps and Versioning · 2.6 Stale-Version Guards on Case and Buyer Writes · 2.7 Money, Basis Points and Rounding · 2.8 Path Resolution and Rejection Precedence · 2.9 Cascade Discipline and Counter Conservation · 2.10 The Settlement Ledger as a Zero-Sum Record
- §3. Business Logic & Workflows — 3.1 The Registry: Consignors, Buying Dealers and Published Arbitration Policy · 3.2 The Block: Recording Sales, Reading Announcements and Releasing Proceeds · 3.3 The Post-Sale Inspection Programme and Its Effect on Arbitration Rights · 3.4 Filing a Claim and the Arbitration Window Gauntlet · 3.5 Evidence Files and Opening Intake Review · 3.6 Seller Response and the Repair-Allowance Negotiation Cycle · 3.7 Transportation Records and Cost Allocation · 3.8 Escalation and the Four Arbitration Outcomes · 3.9 Consequences: Seller Standing, Buyer Privileges, Abandonment and the Deadline Sweep
- §4. Endpoint Definitions (1 status-code paragraph + 42-row table, 4 columns)
- §5. Error Code Catalogue (43-row table, 2 columns)

**Tail confirmation:** `tail -30` ends on the final `| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |` row of the §5 table — a real section boundary, not mid-sentence. No audit footer, no trailing prose after §5.

**Hard Contract reports**

**Contract 1 — Field-Name Coverage: PASS.** 124/124 `entities[].fields[].name` present in PRD backticks (0 missing); 57/57 `endpoints[].input` names present (0 missing); 14/14 computed-response object keys present (0 missing).

**Contract 2 — Rule Coverage: PASS.** 43/43 error IDs appear in §1–§4 narrative (not only in the §5 table); all 48 `validations[]` entries have their `error_id` surfaced in prose next to its trigger condition, and the full 1–48 priority ladder is written out in §2.8; all 9 calculations including the 4 named variants (`NEGOTIATED_ACCEPT`/`ARBITRATOR_AWARD`, rolling/lifetime scorecard) are stated as prose formulas with rounding discipline; both `concurrency_rules` appear with their exact error IDs and 412 status; all 6 state machines' state values are present and all 49 transitions are covered — every state-to-state pair now appears in explicit `A → B` arrow form, with creation (`None → X`) and boolean-flag dimensions described in prose; every constant numeric literal appears verbatim.

**Contract 3 — §3 Path Purity: PASS.** 832 backticked tokens scanned in the §3 range (`## 3.` → `## 4.`): 0 tokens beginning with `/`, 0 bare HTTP-method tokens, 0 method+path combinations. Endpoints are referenced only via state-transition pairs, role + action verb, or capability description. The one URL mention is the §1/§4 mount statement, which is permitted.

Also verified: the §2.2 block is byte-identical to `section-2.2-response-structure.md` (diff shows only the trailing blank separator line before §2.3).

Nothing outside `workspace/` was touched — `worklog.md`, `SCAFFOLD*.yaml` and `INSTRUCTION.md` are untouched, and neither withheld design file was opened. One task-scoped scratch checker remains at `workspace/t2908_field_inventory.py` (re-runnable contract verifier); say the word if you want it deleted.

Orchestrator verification (truncation guard): independently ran `wc -l` (502), listed all 27 headings (§1 through §5 all present and ordered), and read `tail -12` — the file ends on the final `ERR_PAYMENT_EXCEEDS_BALANCE | 422` row of the §5 catalogue, a clean section boundary. Not truncated, so no regeneration needed. Also grepped PRD.md for `harder than expert` and `scaffold`: zero hits, confirming the difficulty directive and scaffold references did not leak. Deleted the leftover scratch verifier `workspace/t2908_field_inventory.py`.

## Step 6: Generate implementation — 2026-09-05T17:22:00.000Z

Subagent summary (verbatim):

Scenario 3 passed 24/24 on a fresh server; scratch removed. Final state below.

## Implementation delivered

`/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/workspace/implementation/`

| file | lines |
|---|---|
| app.py | 73 |
| authz.py | 24 |
| calc.py | 149 |
| envelope.py | 44 |
| errors.py | 106 |
| r_adjudication.py | 156 |
| r_cases.py | 202 |
| r_negotiation.py | 113 |
| r_ops.py | 28 |
| r_psi.py | 76 |
| r_registry.py | 192 |
| r_sales.py | 141 |
| services.py | 554 |
| store.py | 125 |
| util.py | 109 |
| validators.py | 150 |
| start.sh | 10 |
| requirements.txt | 1 |
| **total** | **2253** |

All 16 modules pass `python3 -m py_compile`. `__pycache__` removed; nothing else in `workspace/` except `INSTRUCTION.md`, `PRD.md`, `implementation/`.

## Endpoints

`app.url_map` registers exactly **42 routes** (no `static`): 40 under `/arbitration` plus `POST /_clock/set_current_utc` and `POST /_ops/run-arbitration-sweep` — a 1:1 match with the PRD/scaffold endpoint table. 43 error IDs are wired in `errors.py`.

## start.sh

Reads `$PORT` (`app.py`: `int(os.environ.get("PORT", "10000"))`), binds `0.0.0.0` (verified in `ss -ltn`: `LISTEN 0.0.0.0:23294`), and runs in the foreground via `exec python3 app.py`. It is `chmod +x`. The pip install is guarded by an `import flask` probe so 8 concurrent per-test reboots don't contend on the installer.

## Storage

In-memory only — 14 dicts on the `store` singleton plus `_seq` and the logical `clock`. A grep for `sqlite|json.dump|open(|/tmp|pickle|shelve` across all modules returns nothing. On a fresh boot every collection is length 0 and `GET /arbitration/sales` / `GET /arbitration/cases` both return `data: []` with `total_count: 0`; the clock starts at the declared default `2026-08-01T00:00:00.000Z`. Zero rows are seeded, preloaded, or hardcoded.

## Smoke tests (scratch, since deleted)

Three scenarios, each against a freshly booted server, **all checks passing**:
- Scenario 1 (77 checks) — envelope/meta shape, 401/403 auth, clock monotonicity, registry + duplicate license/policy, sale creation and VIN validation, PSI fees + overlap, intake window math (48h + 24h PSI extension = 72h), evidence + `case_version_after`, review gates, transport leg banding, negotiation/cooldown/supersede, settle, negotiated accept, ledger zero-sum, scorecard, sweep idempotence, pagination.
- Scenario 2 — sweep phases 1/3/4, UNWIND on unsettled (no ledger rows) vs settled (per-party net-zero reversal pair), FRIVOLOUS_DENIED ladder + FEE_HOLD + fee-payment guards, withdraw/refile with `superseded_case_id`, title-claim evidence gates, `ERR_UNWIND_MANDATORY`, PROBATION→BLOCKED at 3333 bps, settlement-hold cascade, `ERR_SELLER_BLOCKED`, reinstate, `psi_clean_waives_rights`.
- Scenario 3 (24 checks) — phase-2 lapsed offer blaming the BUYER, `ERR_ROUND_EXPIRED`, ARBITRATOR_AWARD `min(requested, computed)` under a RED 6000 bps multiplier (180000 from a 300000 base), `ERR_ALLOWANCE_EXCEEDS_CAP`, allowance transport profile 2000/7000/residual, settlement untouched on the allowance branch, three rounds then escalation with all rounds SUPERSEDED, cross-case `ERR_ROUND_NOT_FOUND`, CLAIM_DENIED putting 100% of transport on the buyer with no seller consequence, mileage award via `verified_true_mileage` capped at the policy cap, `ERR_MILEAGE_LIMIT_EXCEEDED`.

Smoke hygiene: high random ports only, PID resolved via `ss -ltnp | grep ":$PORT "`, and only that single PID killed — ports/PIDs used and released were 24167/39179, 24588/63832, 22765/69051, 24628/71844, 24019/77954, 22678/78268, 23740/78532, 23294/78964. Every run ended with "port free"; no broad `pkill` was ever issued. No sibling task directory, no difficulty/corner design file, and no `test_helpers/`/`test_suite/` was read or created; `worklog.md` untouched.

One behavior worth flagging for Step 7: two known-correct results initially looked like bugs in my own scratch assertions, not the implementation — the rolling arbitration rate over 6 in-window sales with 1 upheld claim is 1667 bps (not 2000), and the auto tier note is `"auto tier change at 1667 bps"`.

## Step 5: Generate unit tests — 2026-09-05T18:05:00.000Z

Subagent summary (verbatim):

The suite is complete.

## Deliverables

Both directories are at the **task root** (`/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/`), and a `find` over `workspace/` confirms **no copies** of `test_helpers/` or `test_suite/` were written there.

**`test_helpers/` — 9 files, 1937 lines**
`__init__.py` 17, `api_client.py` 265, `api_errors.py` 100, `assertions.py` 189, `constants.py` 218, `factories.py` 528, `fixtures.py` 90, `test_users.py` 118, `types.py` 412.

**`test_suite/` — 18 files, 6422 lines** (`conftest.py` 21 plus 17 test modules)
`test_01` 325/6 tests, `test_02` 369/6, `test_03` 343/6, `test_04` 397/6, `test_05` 337/6, `test_06` 447/7, `test_07` 332/5, `test_08` 286/5, `test_09` 394/6, `test_10` 458/12, `test_11` 630/16, `test_12` 485/6, `test_13` 381/8, `test_14` 301/7, `test_15` 401/11, `test_16` 302/9, `test_17` 213/4.

## Coverage against the two design indices

**126 tests total — 53 from queue A (difficulty), 73 from queue B (corner).**

A corner-aware checker (`workspace/t2908_scratch/check_all_coverage.py`) parses both design YAMLs, extracts every non-stub instance, and diffs against the `Design:` tags actually emitted:

```
corner non-stub: 73  stub: 37
difficulty non-stub: 23  stub: 0
tests emitted: 126  distinct tags: 96
skipped_total 0
problems no
```

- All 23 difficulty instances and all 73 non-stub corner instances are covered (96 distinct tags = 96 instances).
- **0 instances skipped** by the PRD-first filter — every non-stub instance had verbatim PRD coverage that uniquely derives its asserted outcome.
- Zero untagged, zero dual-tagged, zero tags pointing at stub (`excluded_because`) or non-existent instances, and every `Design:` line is the docstring's last line.
- `check_quotes.py` reports `missing_total 0`: every `PRD: "..."` citation is a verbatim, greppable span of `workspace/PRD.md`.

## Two design-vs-PRD literal conflicts resolved in the PRD's favour

1. The `rbac` instance for shared evidence filing asserts `submitted_by_role == "INSPECTOR"`; PRD line 285 declares the value is either `BuyerRep` or `Inspector`. The test asserts `"Inspector"`.
2. The `complexity_layers` transport-leg instances use `leg_type: "INBOUND"`; PRD line 329 enumerates `INBOUND_TO_AUCTION`, `RETURN_TO_SELLER`, `TO_BUYER_REDELIVERY`. The tests use `INBOUND_TO_AUCTION`.

A third conflict was structural rather than literal: the mileage-diminution calculation instance needs no mileage limit and a 4000 bps cap, which the shared `MILEAGE_POLICY` preset (limit 500, cap 5000) would have rejected with `ERR_MILEAGE_LIMIT_EXCEEDED`, so `test_12` carries a local `MILEAGE_PRESET` that omits `mileage_limit`.

## Verification

`python3 -m py_compile` over all 27 `.py` files → `COMPILE_OK`; `__pycache__` cleaned up afterwards. An AST unused-import scan is clean across every module (the only hits are `conftest.py`'s deliberate `# noqa: F401` fixture re-exports, which is how pytest discovers them). No file in either directory references `implementation` — the tests were written purely against `PRD.md` and the two design indices, and `workspace/implementation/` was never read or created by me. Scratch tooling lives in the task-scoped `workspace/t2908_scratch/`.

Orchestrator verification: `ls -d test_helpers test_suite` confirms both at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing (no stray copies under workspace/, the known Step 5 failure mode). 18 files in test_suite/, 126 collected `def test_` functions. Removed the leftover `workspace/t2908_scratch/` tooling directory so workspace/ holds only INSTRUCTION.md, PRD.md and implementation/. Steps 5 and 6 were launched in a single assistant message, so the implementation generator had physical isolation from test_suite/ (the directory did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-05T18:13:17.409Z

Subagent summary (verbatim):

All 8 rounds green. Final state below.

## Summary

**Iterations run:** 3 full 8-round sweeps (126 tests each round).
- Sweep 1: 58/126 in all 8 rounds (68 failures, deterministic 8/8)
- Sweep 2: 124/126 in all 8 rounds (2 failures, deterministic 8/8)
- Sweep 3: **126/126 in all 8 rounds**

**Tests deleted:** none. Every failure traced to a test-artifact bug (STEP 2 TEST-vs-PRD CONSISTENCY); no PRD-silence or non-derivability collapse was found, so no assertion was removed, relaxed, skipped, or downgraded.

**Fixes to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/test_helpers/assertions.py` — new assertion helper `validate_unpaginated(response)`: the runner's shared `validate_paginated` asserts `meta.limit` is an int `> 0`, which contradicts PRD §2.3 ("`limit` is null and `offset` is 0" on every list route other than the sale list and the case list). The helper validates the 200 + `response_type: "array"` envelope and returns `(rows, meta)` so the tests' own `assert_unpaginated_meta` can do the PRD check.
- `/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/test_helpers/factories.py` — `accept_round` now expects `201`, not `200`: it consumes the newly created `ArbitrationDecision` from `data` (PRD §3.6 Hop 2), and PRD §4 pairs "brings a new record into existence" with `201 Created` returning the created row.

**Fixes to `test_suite/` (all PRD-faithfulness corrections):**
- `test_01` … `test_17` — 82 call sites migrated from `validate_paginated` to `validate_unpaginated`, only on the unpaginated sub-resource routes (announcements, sale inspections, sale/case ledger entries, evidence, negotiation rounds, decision, transport legs, frivolous fees, policy actions). `list_sales` and `list_cases` correctly keep the paginated validator. Imports rewritten per file; the now-unused runner import pruned where nothing else needed it.
- `test_04_transitive_cascades.py::test_a_frivolous_denial_carries_no_seller_consequence_and_posts_no_sale_money` — asserted the three denied sales carry zero ledger rows, but PRD §2.7 says every `SettlementLedgerEntry` "names the sale it belongs to through `sale_id`" and §3.8 Hop 1 posts a `FRIVOLOUS_FEE_ASSESSED` pair per denial. Now asserts exactly that balanced pair per sale at the ladder figures 25000/50000/60000, still proving no sale money (no proceeds, reversal, or allowance) moved. Consistent with `test_12`, which asserts the same pair on the case ledger.
- `test_07_cross_entity_state_dependency.py::test_the_same_settle_succeeds_after_reinstatement_and_the_rate_stays_put` — asserted the scorecard reports `PROBATION`, but PRD §3.9 says the read "recomputes both variants against the current logical clock" and answers with "the `policy_tier` those figures produce", and 4 in-window sales at 2500 bps produce `BLOCKED` (stickiness only pins a tier that is *already* `BLOCKED`). Now asserts `BLOCKED` from the read plus the PRD's actual no-mutation guarantee: the consignor row still reads `PROBATION`, `blocked_at_utc` null, and an unchanged `version`.

**Fixes to `implementation/`:** none. No implementation defect was found; `envelope.unpaginated()`, `r_negotiation.accept` (201 + decision), `services._apply_frivolous` (fee pair attributed to the case's sale) and `calc.tier_for`/`compute_scorecard` were all already the PRD-faithful behaviour, and the tests were brought into line with them.

**Final per-round results:** rounds 1-8 all `126 / 126` passed, 0 failed. No flakiness, no timeouts, no `ServerStartError`, no reap pattern. Verified no stray servers left behind (only self-matching scan processes appeared); `worklog.md` untouched.

Orchestrator verification: independently listed and parsed all 8 `workspace/implementation/results.*.json` (all 8 present, timestamped 18:11, each `passed 126 / total 126 / failed 0`) rather than trusting the claim. Confirmed the subagent left `worklog.md` untouched (6 step headings, no stray Step 7 entry of its own). Sweep was driven from the pre-written `workspace/sweep.sh` script file under `setsid nohup` to avoid both the inline-quoting bug and sweep reaping.

Step 8 decision: NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; this run had 2 `test_helpers/` fixes and 84 `test_suite/` corrections, so Step 8 runs. Note in advance that Step 7 made 0 `implementation/` fixes, so a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here — the test artifacts, not the PRD, were what diverged.

## Step 8: Finalize PRD — 2026-09-05T18:17:29.422Z

Subagent summary (verbatim):

PRD_FINALIZED.md written with two minimal in-line revisions.

## Line counts
- `PRD.md`: 502 lines · `PRD_FINALIZED.md`: 502 lines — 0% line-count delta; 2 of 502 lines revised (0.4%). No sections added.

## Changes
- **§3.6 (accept)** — revise — pinned that accepting an open offer answers `201 Created` with the newly created `ArbitrationDecision` in `data` (not the accepted round) — `implementation/r_negotiation.py:113` (`created(public(decision))`), decision minted at `implementation/services.py:348-370`.
- **§3.9 (scorecard read)** — revise — pinned that the reported `policy_tier` comes from the same tier function the stored tier uses, so the stored tier enters only through the `BLOCKED` stickiness clause; from any non-`BLOCKED` stored tier the read reports whatever the recomputed rolling figures produce, above or below the stored tier — `implementation/services.py:226` (`calc.tier_for(seller["policy_tier"], rolling_sales, rolling_rate)`), `implementation/calc.py:106-118`, surfaced at `implementation/r_registry.py:181-192`.

## Pre-edit search log
**Edit 1 — subject: the HTTP status and response body of `POST …/negotiation-rounds/{id}/accept`, and by extension the 201-vs-200 rule of §4.**
(b) Paths enumerated: `grep "return \(created\|obj\|unpaginated\|arr\)" r_*.py app.py` over every route module, then read `r_negotiation.py` (seller-response → 201 + round; counter → 200 + round; accept → 201 + decision), `r_adjudication.py` (transport leg → 201 + leg; decision → 201 + decision; escalate/withdraw → 200 + case), `r_registry.py` (registrations → 201; fee-payment → 200 + buyer; reinstate → 200 + seller; scorecard → 200 + computed object), `r_cases.py`/`r_sales.py`/`r_psi.py`/`r_ops.py` (claim, evidence, announcement, PSI purchase → 201; open-review, settle, PSI complete, clock, sweep → 200), and `envelope.py` (`created` = `obj(...,201)`). (c) Wording adjustment: scoped the sentence to the accept route alone and justified it by the decision row's creation rather than restating a general rule, so the 200-returning mutators (counter, escalate, withdraw, settle, complete, fee-payment, reinstate) and the other 201 creators keep §4's existing wording untouched.

**Edit 2 — subject: how a `policy_tier` is derived from rolling scorecard figures, and which tier the scorecard read reports.**
(b) Paths enumerated: `grep -rn "policy_tier\|tier_for\|compute_scorecard\|TIER_"` across the implementation → `calc.tier_for` (sole tier function; `BLOCKED` short-circuit first, then `<4` in-window sales → `GOOD_STANDING`, then 2500/1500/800 bps ladder), its only caller `services.compute_scorecard:226`, and that function's two callers: `r_registry.read_scorecard:185` (read, no `touch`) and `services.recompute_seller_standing:253-273` (mutating path, `from_tier` = stored tier, action row only when the tier moves and the target is in `TIER_TO_ACTION_TYPE`, `blocked_at_utc` stamp, settlement-hold cascade). Also checked the tier's non-scorecard readers/writers: `r_registry.reinstate_seller:157-160` (sets `PROBATION` directly, bypassing `tier_for`), `r_registry.create_seller:35` (`GOOD_STANDING` seed), `r_sales.py:119` (settlement's `ERR_SELLER_BLOCKED` check reads the *stored* tier), `store.py:36-38,79` (thresholds and action map). (c) Wording adjustment: confined the new clause to the read's answer and framed it as "the same tier function the stored tier uses", explicitly allowing the reported tier to sit *above or below* the stored one, so it does not imply the read mutates anything, does not touch the de-escalation-is-silent rule of the mutating path, and does not suggest settlement or reinstatement consult the recomputed figures.

## Items deliberately left unedited
- **§2.3 pagination shape** — PRD already states verbatim that the non-sale/non-case list routes are unpaginated with `total_count` = rows returned, `has_more` false, `limit` null, `offset` 0, which is exactly `envelope.unpaginated()` (`arr(rows, None, 0, len(rows))`). The route enumeration in §2.3 also matches the 13 `unpaginated(...)` call sites one-for-one, with only `list_sales`/`list_cases` using `arr(...)`. Pure runner/test-helper artifact bug; no edit. (I also left the untested question of what happens if a client *sends* `limit` to an unpaginated route alone — the impl silently ignores it, Step 7 never exercised it, and asserting either behaviour would be a new claim.)
- **§2.10/§3.8 frivolous-fee ledger attribution** — `services._apply_frivolous:415-416` posts the `FRIVOLOUS_FEE_ASSESSED` pair with `sale_id` = the case's sale and `case_id` = the case, which §2.10 already forces ("Each row names the sale it belongs to through `sale_id`", `case_id` null only for settlement proceeds) together with §3.8 Hop 1. Same holds for `FRIVOLOUS_FEE_OFFSET` (`_apply_unwind:391-392`) and the transport batches on denied outcomes. Pure test-artifact bug; no edit.

Orchestrator verification: ran `diff PRD.md PRD_FINALIZED.md` myself — exactly 2 changed lines (315 and 390), both in-place prose revisions with no added sections and no line-count change, matching the reported edits. `tail` confirms PRD_FINALIZED.md still ends on the §5 catalogue's final row (not truncated). So although Step 7 applied zero implementation fixes, Step 8 was not a no-op: two genuine PRD silences surfaced at the sites the test-artifact bugs pointed to (§3.6 accept returning 201 + the created decision, and §3.9's recomputed-vs-stored tier).

## Step 9: Complete PRD — 2026-09-05T18:43:03.631Z

Run as THREE sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, because a single monolithic Step 9 pass reliably returns a byte-identical file (the scan never actually happens). Pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from running any `cp` so they could not destroy earlier passes' edits. Partition: pass 1 = app/authz/envelope/errors/util/store/validators/r_registry/r_sales; pass 2 = r_cases/r_psi/r_negotiation/r_ops; pass 3 = r_adjudication/services/calc. Each pass was told which paragraphs the previous passes had already touched.

**Aggregate result: 52 edits (43 ambiguity-pins, 9 mismatch-revisions) across 49 changed lines. 502 lines in, 502 lines out; 99,775 → 120,400 chars (+20,625, +20.7%). No new sections; every edit is an in-paragraph insert or revision.**

### Pass 1 summary (verbatim) — infra, registry, sales

## Line counts
- `PRD_FINALIZED.md`: 502 lines / 99,775 chars
- `PRD_COMPLETED.md`: 502 lines / 105,836 chars (**char-delta +6,061**; 16 lines revised in place, no lines added or removed)

## Counts
- ambiguity-pins: **15**
- mismatch-revisions: **1** (§3.2 sale-recording consequence on the consignor)

## Changes
- §2.1 — insert — ambiguity — whitespace-only header counts as blank; neither header is trimmed or case-folded past the presence test, so `"AuctionAdmin "` reaches the authz check and gets 403, and `X-User-ID` is compared verbatim in ownership checks — `authz.py:16-23`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host's real wall clock, not the logical clock — `envelope.py:7-11`, `util.py:41-42`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` (e.g. `abc`, `2.5`) is also `ERR_INVALID_REQUEST`; surrounding whitespace tolerated — `validators.py:132-137`
- §2.4 — insert — ambiguity — client instants accepted with `Z`, an explicit offset, or no zone (read as UTC), then normalised to UTC with exactly three fractional digits on store/echo; startup default reads `2026-08-01T00:00:00.000Z` — `util.py:45-60`, `util.py:26-34`, `r_sales.py:49`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` are wall-clock, the one exception to §2.4, and never coincide with same-request logical stamps; `created_at` ties broken by insertion sequence in lists and in every `created_at`-ranked selector — `store.py:114-116`, `services.py:22`, `util.py:86-88`
- §2.8 (check 4) — insert — ambiguity — a JSON boolean is not an integer; optional fields sent explicitly as `null` behave as omitted and take their default (`seller_response_hours: null` → 24); undefined keys ignored; the future-`hammer_time_utc` rejection lives at this stage — `validators.py:22,31-32,61-70`, `r_sales.py:39-41`
- §2.9 — insert — ambiguity — the version bump is once per request, not once per touch, for a row reached by two cascade paths — `services.py:15-23`
- §3.1 — insert — ambiguity — licence-collision test is exact and case-sensitive with no normalisation (`AB1234` != `ab1234`) — `r_registry.py:17-21`
- §3.1 — insert — ambiguity — both policy booleans are mandatory and must be JSON `true`/`false` — `r_registry.py:89,92`
- §3.2 — insert — ambiguity — `announced_odometer_miles` is a non-negative integer; a future `hammer_time_utc` is `ERR_INVALID_REQUEST` screened before `seller_id`/`buyer_id` resolution — `r_sales.py:36,39-41`
- §3.2 — **revise** — **mismatch** — recording a sale writes nothing onto the `Seller`: stored `lifetime_sales_count`/`rolling_window_sales_count`, rates, `updated_at` and `version` all stay put; the sale counts only through the on-demand scorecard computation — `r_sales.py:42-60` (no `S.touch(seller)`), `services.py:197-227`
- §3.2 — insert — ambiguity — sale-list filters conjoin; bad `settlement_status` → `ERR_INVALID_REQUEST`, while unknown `seller_id`/`buyer_id` yield an empty page with `total_count` 0 rather than 404 — `r_sales.py:69-85`, `validators.py:140-150`
- §3.2 — insert — ambiguity — announcements have no uniqueness or timing guard (same class repeatable, allowed post-settlement / with open cases) and never touch the sale row, so the sale's `version` does not move — `r_sales.py:88-102`
- §3.2 — insert — ambiguity — settle takes no payload and ignores any body; the seller credit row is posted before the buyer debit row — `r_sales.py:112-127`
- §3.9 — insert — ambiguity — `reinstate_note` is >=1 char, non-blank, no upper bound; the `REINSTATE` action carries `from_tier` `BLOCKED`, `to_tier` `PROBATION`, and `rolling_rate_bps_at_action` copied from the *stored* rate (reinstatement recomputes no scorecard) — `r_registry.py:151-171`
- §3.9 — insert — ambiguity — `amount_cents` is non-negative and 0 is a legal payment that still bumps `version`; fee payment is the one buyer-facing write with **no** ownership check, so any `BuyerRep` may pay any buyer's balance — `r_registry.py:122-139`

## Verification
- Tail confirmed intact: file still ends on the final row of the §5 table. No sections added; all edits are in-paragraph.
- Only `workspace/PRD_COMPLETED.md` was written (plus the mandated Step-0 `cp` that created it). SCAFFOLD*.yaml and worklog.md were not read.

### Pass 2 summary (verbatim) — claim intake, PSI, evidence, negotiation, ops

## File state
- `PRD_COMPLETED.md`: **502 lines** (unchanged — no new paragraphs, no new sections), **115,322 chars**.
- Pass 1 left it at 105,836 chars, so **pass 2 alone added 9,486 chars**.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = **144** (36 changed lines: 14 from pass 1, 22 from pass 2).
- Tail intact: file still ends on `| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |`, the final row of the §5 table.

## Counts
**22 edits: 18 ambiguity-pins, 4 mismatch-revisions.** Every one is an in-paragraph insert/revision. **No `cp` was run** — only the Edit tool.

## Changes
- §3.3 — revise — mismatch — PSI purchase guards reordered to actual firing order (sale → `ERR_NOT_SALE_BUYER` → `ERR_SALE_ALREADY_SETTLED` → `ERR_BUYER_FEE_HOLD`); PRD had fee-hold before settled, contradicting §2.8's ladder — `r_psi.py:36-43`
- §3.3 — insert — ambiguity — `fee_cents` is a recorded price only: purchase posts no ledger entry, moves no counter, bumps no version on buyer/sale/seller; the row stores no purchaser identity — `r_psi.py:50-61`
- §3.3 — insert — ambiguity — `findings` is required; a non-array, null, or duplicated family is `ERR_INVALID_REQUEST` (not de-duplicated); stored in submitted order; any `Inspector` may complete any inspection with no ownership test and no identifier recorded; completion touches nothing outside the inspection row — `r_psi.py:64-76`, `validators.py:98-110`
- §3.4 — insert — ambiguity — `superseded_case_id` stores null when omitted; `claim_amount_cents`/`complaint_text` are pure record and never bound any later computation beyond the policy floor — `r_cases.py:82,92,94`
- §3.4 — insert — ambiguity — the superseded-case mismatch `ERR_INVALID_REQUEST` is evaluated after the sale/policy/prior-case lookups, so an unknown `sale_id` reports `ERR_SALE_NOT_FOUND` first — `r_cases.py:46-56`
- §3.4 — insert — ambiguity — `hours_elapsed_at_claim` crosses as a JSON number; `miles_driven_at_claim` is a signed, unclamped subtraction and a negative value passes any limit — `r_cases.py:74,96`, `calc.py:143`
- §3.4 — insert — ambiguity — `psi_extension_applied_hours` is computed independently of `window_hours`, so a matching PSI under an unlimited-window policy stores a non-zero extension beside a null `effective_window_hours` — `calc.py:132-141`, `r_cases.py:70`
- §3.4 — insert — ambiguity — every persisted case necessarily carries `window_eligible` true, since either axis failing rejects the filing — `r_cases.py:76-79,100`
- §3.4 — revise — **mismatch** — the sale's `arbitration_status` moves `NONE → ACTIVE` only from `NONE`; an already-`ACTIVE` sale stays `ACTIVE` and a decided sale stays `RESOLVED` rather than returning to `ACTIVE` — `services.py:149-150`
- §3.4 — insert — ambiguity — the five case-list filters conjoin; `status` is enum-validated; the four identifier filters match verbatim and yield an empty array with `total_count` 0 — `r_cases.py:122-136`
- §3.5 — insert — ambiguity — open-review takes no payload (body ignored) and the status gate precedes all evidence gates — `r_cases.py:179-192`
- §3.5 — insert — ambiguity — both derived readings are recomputed from the whole file inside the single append `version` bump, and never revert to 0/null — `services.py:124-134`, `r_cases.py:153,168`
- §3.6 — insert — **mismatch** — all three answers are legal from both `UNDER_REVIEW` and `COUNTERED`; a supplied `seller_offer_cents` on a non-offer answer is still validated non-negative then discarded; response is 201 with the round row — `r_negotiation.py:29-30,36,51,53`
- §3.6 — insert — ambiguity — every round including `CLOSED`/`TIMEOUT` ones carries a `response_deadline_utc` (inert there) and starts with four null negotiation fields; `round_index` has no ceiling — `services.py:296-314`
- §3.6 — insert — ambiguity — an offer exactly on the cap is accepted; under `max_allowance_bps` 0 every legal offer is refused with `ERR_ALLOWANCE_EXCEEDS_CAP`, never `ERR_UNWIND_MANDATORY` — `r_negotiation.py:41-43`, `calc.py:78`
- §3.6 — revise — **mismatch** — a `DISPUTE` also runs `COUNTERED → ARBITRATOR_REVIEW`, leaving the countered round in `COUNTERED` — `r_negotiation.py:36,47-51`
- §3.6 — revise — **mismatch** — same for `ACCEPT_UNWIND` — `r_negotiation.py:36,49-51`
- §3.6 — insert — ambiguity — counter payload: `buyer_demand_cents` required non-negative (0 legal), `counter_note` required non-blank with no max length, neither compared to the offer or cap — `r_negotiation.py:68-69`
- §3.6 — insert — ambiguity — counter answers 200 with the updated round, not the case — `r_negotiation.py:90`
- §3.6 — insert — ambiguity — the cooldown bars a `DISPUTE`/`ACCEPT_UNWIND` too, is checked before the cap, and only `COUNTERED` rounds hold it open — `r_negotiation.py:38-39`, `services.py:285-293`
- §3.6 — insert — ambiguity — accept ignores any body sent — `r_negotiation.py:95-97`
- §3.6 hop 2 — insert — ambiguity — the negotiated-accept decision has null `decided_by_arbitrator_user_id` and null `requested_allowance_cents`, `fault_party` `SELLER`, a server-generated verbatim `rationale`, 0 in the four other-outcome money fields, and leaves `settlement_status` untouched — `services.py:348-362`, `services.py:337-341`
- §3.9 sweep intro — insert — ambiguity — sweep ignores any body and answers 200 with exactly the four-count tally (no `id`, no `created_at`, no row list) — `r_ops.py:25-28`, `services.py:489-490`

Pass 2 also verified pass 1's edits survived (spot-checked §2.1 whitespace-header and §3.2 seller-untouched revisions plus two more).

### Pass 3 summary (verbatim) — adjudication, transport, outcomes, ledger, standing, sweep phases

## File state after pass 3
- `PRD_COMPLETED.md`: **502 lines** (`wc -l`), **120,400 chars** — unchanged line count vs `PRD_FINALIZED.md` (502), so no structural drift.
- Char delta from **my pass alone**: 115,322 → 120,400 = **+5,078 chars**.
- Cumulative changed lines vs `PRD_FINALIZED.md`: **49** (36 lines from passes 1+2 carrying their 38 edits, plus my 13 lines carrying 14 edits).

## Counts
- **Ambiguity pins: 10**
- **Mismatch revisions: 4**

## Changes (each names the impl site it pins)

- §3.7 — insert — ambiguity — a `TRANSPORT_ALLOCATION` batch is always exactly three rows, written buyer → consignor → auction house, and a share that rounds to 0 still gets its own row (three entries per leg, never omitted) — `services.py:102-108`
- §3.8 — insert — ambiguity — `escalation_note` bounds (>=1 char, non-blank, no upper bound) and the fact it is validated then dropped, persisted on no row at all — `r_adjudication.py:55`
- §3.8 — insert — ambiguity — `requested_allowance_cents` supplied with a non-allowance outcome is still schema-checked as a non-negative integer (`ERR_INVALID_REQUEST` on a negative/non-integer) and only then discarded, the row storing null — `r_adjudication.py:79-80`
- §3.8 — insert — ambiguity — all four buyer-position figures exist on every decision row and default to 0, so an arbitrated allowance and both denials report `total_buyer_payout_cents` 0; only `UNWIND` ever fills refund/offset/payout — `services.py:337-340`
- §3.8 — revise — ambiguity — `computed_award_cents` is 0 (not merely `allowance_cents`) on the two non-allowance outcomes; the award formula is not evaluated on a denial — `services.py:447-455`
- §3.8 — revise — mismatch — "no seller consequence of any kind" on `CLAIM_DENIED` contradicted the code: narrowed to no *standing* consequence and no refresh of the six stored scorecard figures, while `open_claim_count` -1 and `version` +1 still happen — `services.py:475-480`
- §3.8 — revise — mismatch — the third frivolous claim reaches `SUSPENDED` from whatever privilege status the buyer held (`ACTIVE → SUSPENDED` as readily as `FEE_HOLD → SUSPENDED`); the count test outranks the balance test — `services.py:421-424`
- §3.8 — insert — ambiguity — rendering a decision supersedes no negotiation rounds and bumps no round's `version`; a round left `COUNTERED` by a dispute stays `COUNTERED` after the case is decided — `services.py:440-481` (no `supersede_rounds` call)
- §3.9 — revise — mismatch — `rolling_window_upheld_count` is **not** restricted to in-window sales: it counts upheld decisions against any of the consignor's sales, filtered on `decided_at_utc` alone (hence rates above 10000 bps are reachable, `rate_bps` applies no clamp) — `services.py:185-194`, `services.py:209-213`, `calc.py:100-103`
- §3.9 — insert — ambiguity — a `SellerPolicyAction` is appended on any move *into* `WATCH`/`PROBATION`/`BLOCKED` regardless of direction (a downward `PROBATION → WATCH` appends `WATCH_LIST`); a no-move recomputation appends nothing yet still refreshes figures and bumps `version` — `services.py:261-268`
- §3.9 — insert — ambiguity — `blocked_at_utc` and the hold cascade belong to the transition into `BLOCKED`, so a later upheld decision on an already-blocked consignor re-runs neither; and the deciding case's own sale is never held because its `arbitration_status` is already `RESOLVED` when the cascade walks — `services.py:246-247`, `services.py:269-273`, `services.py:475-478`
- §3.9 — insert — ambiguity — phase 3's boundary is **strict**, and the minted `TIMEOUT` round carries the server-generated `response_note` `seller response timed out` — `services.py:529-531`
- §3.9 — insert — ambiguity — phase 4's 48-hour grace boundary is **strict** — `services.py:543`
- §3.9 — insert — ambiguity — each phase feeds exactly one counter and they never overlap: `rounds_expired` excludes the round phase 3 mints, `cases_expired` excludes the cases phases 2/3 push into `ARBITRATOR_REVIEW` — `services.py:489-490, 511, 536, 552`

## Verification
- **Passes 1 and 2 survive.** Spot-checked pass 1's §2.1 blank-header sentence and pass 2's §3.6 cooldown clause; all 36 previously-changed lines remain in the diff set.
- **Tail intact**: file still ends on the last row of the §5 error-code table.
- **No `cp` was run** — every change was a surgical `Edit` against the existing `PRD_COMPLETED.md`.

Two candidate silences deliberately left alone as derivable rather than genuine gaps: a zero-mile leg costing exactly the 8500-cent dispatch fee (already implied by "on every leg regardless of distance"), and the phase-2 guard that only moves a parent case still in `NEGOTIATION` (unreachable given every other path supersedes `OPEN` rounds).

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` exists: 502 lines, 120,400 chars, 27 headings (§1–§5 structure intact), tail still on the final §5 error-code row — not truncated.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → differs, so the scan genuinely ran (a byte-identical Step 9 output would have meant it did not). 49 changed lines, +20,625 chars (+20.7%) over PRD_FINALIZED.md.
- Line count held at 502 throughout all three passes, confirming every edit was an in-paragraph insert/revision with no new sections and no structural drift.

PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
