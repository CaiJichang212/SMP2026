# P11 prompt-learning final release verification

The final P11 archive passed the independent release verifier on 2026-09-14.

| Evidence | Value |
| --- | --- |
| Archive | `artifacts/submission/starnet-p11-prompt-learning-20260914.zip` |
| Archive SHA-256 | `5568d38f70974bcc9b3f6d78eb36dd23b81774801dc597cffa81b3bf9c8ec739` |
| Final model SHA-256 | `04a91da1a7e073ffe3139860f60eb9e4a0c30d567ac2ab22a161edf9f2d520ac` |
| Activation report SHA-256 | `438b8fe498e4ea2f649bf3e297cdc39972865cbf2233788a23c36bf325b9ceae` |
| Python 3.9 / modern action SHA-256 | `1aae7c69c5bffa93a6eabe19d1c08b42e23db705d623a93e56be71db83e65fbb` |
| Python 3.9 / modern local score | `746.7619440524936` |
| Release gate | passed |

The Python 3.9.25 / NetworkX 3.1 and Python 3.12.3 / NetworkX 3.6.1 final-ZIP
executions have the same archive hash, model hash, action hash, and score. Both
entry reports are complete and have `entry_gate_passed=true`,
`final_zip_execution=true`, and `unreleased_candidate_assembly=false`.

`verify_p11_release_archive.py` was run as the sole compute task in systemd unit
`smp2026-p11-final-verify-20260914.service` with `CPUQuota=75%`, `CPUWeight=10`,
`MemoryHigh=1G`, `Nice=19`, `CPUAffinity=1`, user `ubuntu`, and the repository as
its working directory. It completed successfully in 538 ms, using 404 ms CPU,
376 KiB peak memory, and no swap.

The verifier confirmed unique ZIP members, canonical file bytes, source manifest
coverage, activation evidence identity, final-entry identity, exact reconstruction
of the tested unreleased strategy body, and that only P11 qualification metadata
changed during activation. The official platform score remains unknown until this
exact archive is submitted; the local entry score is not an official-score claim.
