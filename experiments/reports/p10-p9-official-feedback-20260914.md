# P9 official feedback and next attribution

The user reports that `starnet-p9-bounded-response-20260913.zip` received an
official score of **761.9467**. Its SHA-256 is
`4df04b79f44d8bc7a21cad890bf6bc241531b976899cafbbdc5574bb6772f460`.
The historical official best remains
`starnet-public-greedy-experimental-20260908.zip` at **765.8400**.

This feedback does not change the conclusions of the bounded-response release
report. The `[-100,100]` communication bound was established by 108 public
mechanism observations, and the P9 archive passed its declared local
development, confirmation, Python 3.9, generated-entry and real-LLM checks.
Those checks established implementation correctness and improvement on the
registered boundary-stress distribution. They did not establish that official
hidden seeds often reach the response bound. The unchanged official aggregate
is evidence that this correction did not produce a measurable platform gain
at the displayed precision.

The next attribution therefore targets policy differences already present in
the historical official-best archive:

- historical experimental pools observed first responses across untried
  targets, while P9 normally uses a fixed population prior on mixed graphs;
- historical experimental exposes every positive-gain shield/cut, while P9
  applies direction and communication-ROI filters;
- P9 closes structure candidates on overwhelmingly positive public graphs and
  switches those graphs back to pooled response estimates.

The factor experiment is registered separately in
`experiments/manifests/p10-greedy-factor-attribution-20260914.json`. It uses
only previously consumed cases for mechanism attribution. It is not a new
holdout or promotion result and does not modify production policy.
