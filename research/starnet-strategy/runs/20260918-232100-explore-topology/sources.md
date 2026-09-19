# Online source check, 2026-09-18

| Source | Verified retrieval | Use / limitation |
| --- | --- | --- |
| DeGroot, Reaching a Consensus (1974), DOI 10.1080/01621459.1974.10480137 | Crossref works API HTTP200, matching title | Stationary influence as a hypothesis; no claim that official engine is exactly DeGroot |
| Kempe, Kleinberg, Tardos, Maximizing the Spread of Influence through a Social Network (2003), DOI 10.1145/956750.956769 | Crossref title search HTTP200, matching title | Budgeted marginal gain baseline; continuous signed opinions and graph removal do not inherit IC/LT approximation guarantees |
| Golovin & Krause, Adaptive Submodularity (arXiv:1003.3967v5) | export.arxiv.org/api/query?id_list=1003.3967 HTTP200, matching authors/title/abstract | Feedback-adaptive choice; no assertion our objective is adaptively submodular; v5 corrects a theorem under additional assumptions |

Crossref free-text query for the third source returned an unrelated 2020 work;
discarded it and verified the exact arXiv record instead. No third-party policy
code installed. Existing NetworkX supplies graph generators and components.

Links: https://doi.org/10.1080/01621459.1974.10480137 ,
https://doi.org/10.1145/956750.956769 , https://arxiv.org/abs/1003.3967 .

Additional search leads (Crossref HTTP200, title/DOI only): Opinion Maximization
in Social Networks,10.1137/1.9781611972832.43; Active Opinion Maximization in Social
Networks (Liu,Kong,Yu),10.1145/3219819.3220061; Dynamic Opinion Maximization in
Social Networks,10.1109/TKDE.2021.3077491. The Active paper's metadata contains no
abstract; these leads do not substantiate algorithm claims or implementations.
