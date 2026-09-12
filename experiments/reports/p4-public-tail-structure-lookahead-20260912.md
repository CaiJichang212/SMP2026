# P4 public tail structure lookahead

## Hypothesis

One-step ROI can be suboptimal near the end of the budget: a 2-point
communication may consume budget needed for a 5-point shield or 3-point cut.
The candidate compares a communication-only tail with every currently legal
structure action followed by the same greedy communication allocator.

All planning uses only scans, remaining budget, and successful public action
returns. Hypothetical opinions and topology remain in `PredictiveState`; they
are never written to `Blackboard`. The allocator recomputes connected-component
influence after every hypothetical action and therefore excludes a shielded
target automatically. A real action is followed by a fresh plan.

## Exploratory intervals

An earlier temporary diagnostic screened narrower intervals on 39 pairs across
existing, independent, and holdout blocks. It found no terminal-score change:

| Budget interval | Triggers | Wins | Ties | Losses |
| --- | ---: | ---: | ---: | ---: |
| `[5, 7)` | 0 | 0 | 39 | 0 |
| `[5, 9)` | 1 | 0 | 39 | 0 |
| `[5, 15)` | 5 | 0 | 39 | 0 |

Those exploratory runs used a temporary script that was subsequently replaced
after review found that it materialized hypothetical states as temporary
`Blackboard` instances. They are recorded only as exploration history and are
not attributed to the final reproducible implementation.

## Reproducible screen

The corrected implementation reran the wider `[5, 25)` interval on every
existing and independent 50-node family, one paired seed per family:

```bash
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_tail_structure_lookahead.py \
  --blocks existing independent --repetitions 1 --budget-low 5 --budget-high 25 \
  --candidate-limit 64 \
  --output experiments/reports/p4-public-tail-structure-lookahead-20260912.json
```

The experiment runner retains up to 64 scored candidates so low-ROI structure
actions remain visible to the lookahead, while the production controller uses
24. The first action uses the same global sort, so enlarging the retained tail
must not change the selected top candidate when lookahead is disabled. As an
implementation control, every seed is also run with an unreachable lookahead
interval; its score, action counts, and failure count must exactly match the
production `RuntimeController` baseline.

| Pairs | Off-control matches | Triggers | Mean delta | Wins | Ties | Losses | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 10 | 4 | 0.0 | 0 | 10 | 0 | 0 |

The four triggers occurred in three seeds: `ba_negative_hubs` (one),
`sbm_violent_cluster` (two), and independent `two_block_bridge` (one). In all
three, baseline and candidate action counts were identical. The lookahead only
changed action order; it did not change the terminal portfolio or score.

## Conclusion

Do not promote or wire this candidate into `RuntimeController`. Under the
verified local linear settlement model, repeated one-step rescoring already
reaches the same terminal action portfolio as this bounded tail planner. The
extra planning cost has no observed benefit. A future structural experiment
needs a mechanism that changes the terminal portfolio, such as a qualified
multi-action topology interaction, rather than another ordering rule.
