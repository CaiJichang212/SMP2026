# Expected-clipped untried prior: negative development result

This experiment was preregistered and committed before execution in
`p9-expected-clip-development-20260913.json`. It used only the already consumed
901 development seeds across four families and the `near_upper_bound` and
`saturated_hubs` shifts. Confirmation remained closed and repetition 902 was
not opened after the stopping rule fired.

The candidate replaced `min(E[15r] * slot, room)` with the analytic
`E[min(15r * slot, room)]` for an untried node on a mixed/risky graph, with
`r ~ Uniform(0.2,1.5)`. All other bounded P8 behavior stayed fixed. For example,
at first-slot room 10 the candidate prior is `8.7435897`, compared with the
current clipped-mean value 10.

Across all eight paired cases, the terminal score delta was exactly zero:
`0 wins / 8 ties / 0 losses`, mean/minimum/maximum all `0.0`.

- All four `near_upper_bound` action sequences were identical.
- Saturated ER901 reordered 17 intervention positions but retained the exact
  same action multiset and terminal score.
- Saturated BA901 reordered 11 intervention positions with the same action
  multiset and terminal score.
- Saturated SBM901 reordered two intervention positions with the same action
  multiset and terminal score.
- Saturated WS901 was identical in both action order and score.

The transformed expectation can change communication priority, but the changed
ordering reached the same terminal state on every affected case. It provided no
score evidence to justify extra policy complexity. This arm stops here and is
not part of the bounded release.

Full action sequences and paired results are in
`p9-expected-clip-dev901-20260913.json` (SHA-256
`d8f3160b82e5526f79492d7513f90a583835bcb733879649e6c1e4af3fb3e504`).
Experimental policy SHA-256:
`10be297c79e04d2ceda39324228b9b3ca2044f6a77f411216f3e8f828a53b067`.
Frozen P8 comparator SHA-256:
`30326ab80cee936c6feb57ec01722eafa0994e2d171d606e6f439a3106f334ca`.
