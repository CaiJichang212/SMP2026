# P10 evidence-gated online response mixture results

## Outcome

The preregistered gate requires at least four uncensored public first responses
and posterior probability at least 0.95 for the aligned or inverse model. Until
then, every untried target receives exactly the fixed 12.75 prediction. Tried
targets always use their own public response.

On all 18 previously consumed cases:

| Contrast | Mean | Minimum | W/T/L |
|---|---:|---:|---:|
| gated minus fixed | +19.6472 | 0.0000 | 8/10/0 |
| soft minus fixed | +21.8562 | -16.6186 | 9/7/2 |
| gated minus soft | -2.2091 | -25.2913 | 3/11/4 |

The gate removed both soft-mixture regressions while retaining positive gain in
every registered correlated case. Its lower mean than soft is the declared
cost of waiting for evidence.

## Strata

| Consumed stratum | Gated minus fixed | Soft minus fixed | Gate activations |
|---|---:|---:|---:|
| legacy independent (6) | 0.0000 | -0.8470 | 0/6 |
| centered independent (4) | 0.0000 | -2.9264 | 0/4 |
| persona aligned (4) | +34.4401 | +48.5777 | 4/4 |
| persona inverse (4) | +53.9723 | +53.9723 | 4/4 |

The independent cases never crossed the evidence gate and were action-for-action
equivalent in final score to fixed. Aligned gates opened after 5, 11, 5 and 6
accepted observations. Inverse gates opened after 7, 10, 8 and 7 observations.
The minimum-four-sample rule was therefore necessary but not sufficient; the
posterior threshold delayed adaptation when evidence was weaker.

## Behavior and boundaries

Gated and fixed first diverged in the eight correlated cases only. Under
unrestricted structure all eight divergences were ranking-only. Under the full
gate, five were ranking-only and three also changed the surviving candidate set
through the communication-ROI filter. The response model remains injectable as
a callable; it does not patch planner globals.

Unrestricted and full-gate scores were identical in all 18 cases for soft,
gated and fixed estimators. This experiment does not supply new structure-gate
evidence.

The pure ledger is implemented in `src/starnet/policy/public_response_mixture.py`.
It imports no scripts or environment implementation, reads no Blackboard, and
stores only persona-tagged public response observations plus local predictions.
All six arms had zero action failures, nonnegative budgets and at most 87
actions. No observation was censored in this ordinary-weight cohort.

## Evidence limits

Every case was consumed before this experiment. The result supports the gate's
mechanism and removes the observed transient losses, but cannot qualify a
production policy. A new frozen distribution must test independent, aligned,
inverse, partially correlated and censored response regimes together with the
intended complete structural planner.

The compact report is `p10-gated-online-mixture-20260914.json`. The ignored full
trace has SHA-256
`b4d185023b705221ec8aba1f01a9100e2ba54ed875e82dd71eb73849769615fd`.
