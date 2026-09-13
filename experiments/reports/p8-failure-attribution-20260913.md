# P8 frozen-failure attribution

## Scope

This diagnostic replays three already observed P7 failures. It opens no new
confirmation cohort and rejects repetition 601 or later. Seed response factors
remain private to `LocalPublicEnvironment`; the policy receives only scan and
successful action returns.

For each case, the runner locates the first action where mean rollout differs
from its current `public_greedy` baseline. It then replays the common public
history twice, forces one of those two first actions, and fixes both branches
to `public_greedy` for every later decision. The terminal difference therefore
isolates the first divergent action from later rollout replanning.

## Results

| Family / repetition | Budget | Mean-rollout action | Baseline action | Predicted gain | Actual first-action counterfactual | Full episode delta | Attribution |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| er_balanced / 402 | 75 | shield 29 | communicate 17 | +1.8482 | -13.9830 | -13.9830 | response estimate |
| lollipop / 301 | 75 | shield 45 | cut 36-50 | +3.2575 | -49.1650 | -49.1650 | response estimate |
| bipartite / 303 | 75 | cut 14-26 | communicate 34 | +1.4247 | -11.9020 | -11.9020 | response estimate |

All three divergences occur on the first intervention after the full scan,
before any real response has been observed. In every case the forced-first
counterfactual equals the full rollout loss. The failure is therefore present
in the first mean-response comparison; repeated receding-horizon plan changes
do not create or amplify these three losses.

The predicted margins are small, from +1.42 to +3.26, while realized losses
are much larger. This supports treating unobserved-response uncertainty as the
primary mechanism. It does not identify a universal numeric threshold: the
three cases were selected because they had already failed, so fitting a margin
to them would be circular. A defensible next candidate should change the
uncertainty model or gather public response evidence, then be frozen and tested
on a separate cohort. It should not tune a cutoff on these cases and relabel
the result as confirmation.

The lollipop failure also shows that the issue is not limited to choosing
structure instead of communication: mean rollout replaced the baseline cut
with a shield. The relevant comparison is the complete response-dependent
continuation after each legal first action.

## Reproduction

```bash
uv run python scripts/attribute_p8_failures.py \
  --output experiments/reports/p8-failure-attribution-20260913.json
uv run python -m unittest tests.unit.test_p8_failure_attribution -v
```

The machine-readable report includes both forced branches, action counts,
remaining budget, prediction error, full-episode replay, and an explicit empty
list of policy hidden-response inputs.
