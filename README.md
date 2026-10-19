# NFL Pick'em

A two-player NFL pick'em at **https://nfl.kosar.sk**. Each week both players pick the winner of every game. Picks lock at kickoff, scores come from ESPN, and the results page keeps weekly and season totals.

## How it works

- **Games page** (`/`): the current week's games. Click a team to pick it, click the other team to change your mind. Each game locks when it kicks off. You can see the other player's picks, and a coloured bar shows whether you got it right. Browse other weeks at the bottom.
- **Results page** (`/results`): correct picks per player for every week, plus the season total.
- **Scoring:** one point per correct pick. A tie counts as a miss for both players, and so does a game you didn't pick. Regular season only (weeks 1–18).
- **Data:** a Kubernetes CronJob runs `python -m app.sync` every hour. It pulls last, current and next week from ESPN's public scoreboard JSON (the full season once a day) and stores schedule and final scores. A pick is correct when it matches the stored winner, so results show up within an hour of a final whistle with no separate grading step. On Tuesday, after Monday night's game is final, the games page moves to the next week.

ESPN's API is free but undocumented. All ESPN-specific code is in `app/espn.py`, so switching providers means rewriting that one file.

## Stack

Python 3.13, FastAPI, server-rendered Jinja pages, SQLite on a 1 GiB `local-path` volume. One container image serves both the web app and the sync job.

```
app/            web app, ESPN client, sync job, templates, CSS
tests/          pytest suite (ESPN is mocked)
k8s/            Kustomize manifests: Deployment, Service, Ingress, PVC, CronJob
deploy/         Argo CD Application to copy into the cluster repo
scripts/        demo data for local development
.github/        CI (tests) and Release (build image, bump tag)
```

## Deployment flow

```
push to main ──► GitHub Actions: tests ─► build image ─► push ghcr.io/xkosarf/nfl-picks:sha-xxxxxxx
                                                      └► commit new tag to k8s/kustomization.yaml
                                                                   │
Argo CD (k3s-hetzner) watches k8s/ on main ◄───────────────────────┘ ──► rolls out nfl.kosar.sk
```

No cluster credentials live in GitHub; Argo CD pulls.

## One-time setup

### 1. DNS

At websupport.sk add an **A record** `nfl` → the Hetzner node's public IP (same target as `argocd`, `grafana` and `lab`).

### 2. First image build

Push this repo to `github.com/xkosarf/nfl-picks`. The **Release** workflow builds the first image and commits its tag. Then make the image public so the cluster can pull it without credentials: GitHub → your profile → **Packages** → `nfl-picks` → **Package settings** → **Change visibility** → Public. (The image contains no secrets.)

### 3. Passwords and the Secret

Generate a password hash for each player. With Python 3 installed, from this repo:

```bash
python3 -m app.auth          # prompts for the password, prints scrypt$...
```

Or with the image: `docker run --rm -it ghcr.io/xkosarf/nfl-picks:<tag> python -m app.auth`.

Create the namespace and the Secret (kept out of git on purpose):

```bash
kubectl create namespace nfl-picks
kubectl -n nfl-picks create secret generic nfl-picks-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=USER1_EMAIL='filip@example.com' \
  --from-literal=USER1_NAME='Filip' \
  --from-literal=USER1_PASSWORD_HASH='scrypt$16384$8$1$...' \
  --from-literal=USER2_EMAIL='friend@example.com' \
  --from-literal=USER2_NAME='Friend' \
  --from-literal=USER2_PASSWORD_HASH='scrypt$16384$8$1$...'
```

Use single quotes around the hashes: they contain `$`. To change a password later, update the Secret and run `kubectl -n nfl-picks rollout restart deploy/nfl-picks`.

### 4. Register the app with Argo CD

Copy `deploy/nfl-picks-app.yaml` into the cluster repo as `clusters/k3s-hetzner/nfl-picks/nfl-picks-app.yaml` and push. The `cluster-root` app picks it up, and Argo CD deploys everything in `k8s/`. cert-manager issues the Let's Encrypt certificate through the existing `letsencrypt-prod` issuer.

On first start the app loads the whole season from ESPN in the background, so the games page fills within a few seconds.

### Checks

```bash
kubectl -n nfl-picks get pods,ingress,certificate
kubectl -n nfl-picks create job --from=cronjob/nfl-picks-sync sync-now   # run a sync right away
kubectl -n nfl-picks logs job/sync-now
```

## Cluster fit

The manifests follow the k3s-hetzner conventions: `traefik` ingress class on the `websecure` entrypoint, `letsencrypt-prod` ClusterIssuer, `local-path` storage, and the Kyverno policies (pinned `sha-` image tags instead of `:latest`, CPU and memory limits, non-root with dropped capabilities and a read-only root filesystem).

The Deployment uses the `Recreate` strategy because SQLite and a `ReadWriteOnce` volume shouldn't have two app pods at once. The sync CronJob mounts the same volume, which works because the cluster is a single node.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | — | Required. Signs the login cookie. |
| `USER1_EMAIL`, `USER1_NAME`, `USER1_PASSWORD_HASH` | — | Player 1. Same for `USER2_…`. Up to 4 players are supported. |
| `DATABASE_PATH` | `/data/nfl.db` | SQLite file. |
| `DISPLAY_TZ` | `Europe/Bratislava` | Kickoff times are shown in this zone. |
| `NFL_SEASON` | ESPN's current season | Set it to pin a season, e.g. `2026`. |
| `COOKIE_SECURE` | `true` | Set `false` for local http. |

## Local development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q

export SECRET_KEY=dev COOKIE_SECURE=false DATABASE_PATH=./data/dev.db
export USER1_EMAIL=me@example.com USER1_NAME=Me USER1_PASSWORD_HASH="$(echo devpassword | python -m app.auth)"
python scripts/seed_demo.py        # made-up week; or `python -m app.sync` for real ESPN data
uvicorn app.main:app --reload      # http://localhost:8000, sign in with devpassword
```

## Later

- Playoffs: ESPN serves them as `seasontype=3`; scoring would need weeks beyond 18.
- Backups: `kubectl -n nfl-picks exec deploy/nfl-picks -- python -c "import sqlite3; sqlite3.connect('/data/nfl.db').backup(sqlite3.connect('/tmp/b.db'))"` then `kubectl cp`.
