# P10 online response mixture results

## Result

The online mixture completed all 18 previously consumed cases with zero action
failures, nonnegative remaining budget and at most 87 actions. Its initial
prediction is exactly the fixed prior (`12.75`) for every persona. All later
changes came from public, uncapped first-response observations; posterior state
was kept outside Blackboard.

| Mixture minus comparator | Cases | Mean | Minimum | W/T/L |
|---|---:|---:|---:|---:|
| fixed, unrestricted | 18 | +21.8562 | -16.6186 | 9/7/2 |
| pooled, unrestricted | 18 | +28.7142 | -9.9484 | 14/2/2 |
| fixed, full gate | 18 | +21.8562 | -16.6186 | 9/7/2 |
| pooled, full gate | 18 | +28.7142 | -9.9484 | 14/2/2 |

The structure arms were identical on all 18 cases for mixture, pooled and
fixed response estimators. These ordinary cases therefore provide response
model evidence only; they add no evidence for removing or retaining structure
gates.

## Correlation strata

| Consumed stratum | Mixture minus fixed | W/T/L |
|---|---:|---:|
| legacy independent, six cases | -0.8470 | 0/5/1 |
| centered independent, four cases | -2.9264 | 1/2/1 |
| persona aligned, four cases | +48.5777 | 4/0/0 |
| persona inverse, four cases | +53.9723 | 4/0/0 |

The mixture learned both correlation directions instead of assuming that peace
must always respond more. Mean final posterior weights were:

| Stratum | Independent | Aligned | Inverse |
|---|---:|---:|---:|
| legacy independent | 0.999525 | 0.000034 | 0.000442 |
| centered independent | 0.999995 | 0.000005 | 0.000000001 |
| persona aligned | 0.000028 | 0.999972 | approximately 0 |
| persona inverse | 0.0000015 | approximately 0 | 0.999999 |

Thus the likelihood update identifies the registered generating model from
public observations. It also shows a remaining risk: temporary posterior
movement can alter early actions before an independent model dominates,
causing the two independent-distribution losses. A production candidate needs
a preregistered confidence or shrinkage rule and new validation; this consumed
cohort cannot qualify it.

## Behavioral changes

Against fixed response, mixture changed the first selected action in 17/18
cases under unrestricted structure; all 17 were ranking-only because both
selected actions were present in both candidate sets. Under the full gate, 15
were ranking-only and two also changed the structure set through the
communication-ROI filter. Against pooled response, unrestricted first
divergences were ranking-only in all 18 cases; under the full gate, six also
changed the gated candidate set.

The mixture accepted 219 public first observations per structure arm and
censored none in this ordinary-weight cohort. The 0.1 independent-density
component kept a model from receiving zero likelihood after one
model-inconsistent observation. Tried targets always used their own public
first response rather than a population prediction.

## Evidence

The compact machine-readable report is
`p10-online-response-mixture-20260914.json`. The 70 MB full action, candidate,
posterior and observation trace remains ignored under `experiments/raw/` with
SHA-256 `1da0004fc2fd79e067cfd51350f884f543741b1c03ef30084dfb044506727797`.
All cases were consumed before this experiment and are not a new holdout.
