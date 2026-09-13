# P9 response-bound development interim result

This is the prespecified boundary-mechanism subset only. It contains 16/56
development cases and does not open confirmation or authorize production.
The remaining five shifts have not started because the initial `comm_left < 3`
and initial `w < -100` rollout semantics are under separate review.

## Frozen execution

- Repetitions: 901 and 902.
- Families: resampled ER, BA, WS and SBM.
- Shifts: `near_upper_bound` and `saturated_hubs`.
- Arms: current bounded source, unchanged submitted P8 ZIP, unchanged
  official-best historical experimental ZIP.
- Current P8 policy SHA-256:
  `51b2a003a4b01afd21453db2c1f26d8bf381558c66fabef8d2d201e96f97f96d`.
- The report pins all build `INLINE_MODULES`, submission config/prompts, seed
  generator, capped simulation environment and experiment runner. Every case
  rechecks the current source snapshot before and after execution.
- Confirmation remained closed. Coverage13 was not run in this priority batch.

## Paired results

| Comparison | Cases | Mean gain | Minimum | W/T/L |
|---|---:|---:|---:|---:|
| bounded source vs submitted P8 | 16 | +41.3797 | +0.3441 | 16/0/0 |
| bounded source vs official-best experimental | 16 | +36.1044 | -110.1658 | 13/0/3 |
| submitted P8 vs official-best experimental | 16 | -5.2753 | -119.3859 | 4/5/7 |

| Shift, bounded vs submitted P8 | Cases | Mean gain | Minimum | W/T/L |
|---|---:|---:|---:|---:|
| `near_upper_bound` | 8 | +58.5367 | +47.2578 | 8/0/0 |
| `saturated_hubs` | 8 | +24.2227 | +0.3441 | 8/0/0 |

Against the official-best experimental archive, `near_upper_bound` gained
56.6727 on average in all eight cases. `saturated_hubs` gained 15.5362 on
average with five wins and three losses. The losses were both BA repetitions
(-102.2994 and -110.1658) and WS repetition 902 (-2.3895). These losses keep
the broad strategy-selection criterion distinct from the response-bound
correction criterion.

## Integrity checks

Each arm completed 16 finite-score cases with zero action failures and zero
P8 planning errors. Remaining budget was never negative and no run exceeded
87 environment actions. Every row contains the ordered action log, public
return, success flag, budget before/after, action-log hash, seed hash and
source/archive hashes in `p9-bounded-development-initial16-20260913.json`.
