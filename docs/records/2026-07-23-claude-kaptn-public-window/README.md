# Record: Claude-Kaptn public-window exposure audit — ZERO exposure

**Conclusion: no third party ever viewed, cloned, forked, starred, or
watched `MicahAI/Claude-Kaptn` during its entire time as a public
repository. The MIT-licensed code never left our machines. This is a
permanently closed non-issue.**

## Timeline (UTC)

| When | Event |
|---|---|
| 2026-07-23 17:05:33 | Repo created **public** (`created_at`, repo_state.json) |
| 2026-07-23 (day) | v1.0.0 → v1.15.2 developed and pushed (~35 tags) |
| 2026-07-24 ~00:05 | Visibility flipped **private** (`gh repo edit --visibility private`), pending licensing decision (freemium: single client free / Fleet paid — ADR-0011) |
| 2026-07-24 00:17:14 | Evidence in this folder captured (captured_at_utc.txt) |

Public window: **~7 hours**, fully inside GitHub's 14-day traffic
retention at capture time — so the data below covers the repo's entire
public life, not a sample.

## Evidence (raw GitHub API responses, this folder)

| File | Endpoint | Result |
|---|---|---|
| traffic_clones.json | `/traffic/clones` | **0 clones, 0 unique cloners** (all 14 daily buckets zero) |
| traffic_views.json | `/traffic/views` | **0 views, 0 unique visitors** |
| traffic_referrers.json | `/traffic/popular/referrers` | empty — no inbound source |
| traffic_paths.json | `/traffic/popular/paths` | empty — no page ever visited |
| repo_state.json | `/repos/...` | forks 0 · stars 0 · watchers 0 · network 0; visibility private |
| forks.json / stargazers.json | enumerations | both empty arrays |

Captured via `gh api` authenticated as repo owner **MicahAI**
(traffic endpoints require push access). Owner's own plugin-marketplace
installs pull via the API zipball and do not register as clones; no
third-party activity of any kind appears.

## Why this matters

The repo carried an MIT license while public. Had anyone cloned it in
that window, that snapshot would be irrevocably MIT in their hands.
The zero-across-the-board traffic data shows no such snapshot exists,
so **any future licensing choice (BSL, AGPL-core + commercial, fully
proprietary) applies cleanly with no grandfathered public copy.**
