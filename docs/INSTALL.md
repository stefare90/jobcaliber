# Install on a server

Everything needed to get from a fresh machine to a running jobcaliber — written so that a human
or an agent can follow it top to bottom. Every step ends with a **check**: if the check fails, do
not continue.

The end state:

| Process | Runs as | Listens on |
|---|---|---|
| `jobcaliber-worker` | systemd user unit | — (it calls the boards and the engine) |
| `jobcaliber-web` | systemd user unit | `0.0.0.0:8000` (LAN, firewall-restricted) |
| `rizzo` (scoring engine) | system unit on the **model host**, started on demand | `0.0.0.0:8017` |

> **Single machine?** All three run on it; the engine as a system unit started by the worker
> (see step 6). **Two machines?** The controller runs web + worker, the model host runs only the
> engine — see [the split setup](#split-setup-controller--model-host).

Total disk: ~5 GB. No root is needed except for the firewall.

---

## 0. Prerequisites

```bash
python3 --version                       # 3.11 or newer (uv installs its own if missing)
git --version
curl --version > /dev/null
free -g                                 # 8 GB of free RAM is enough for the 4B model
df -h ~ | tail -1                       # ~5 GB free
```

Optional but recommended on x86_64 Linux with an AMD/NVIDIA iGPU or dGPU: a working Vulkan
driver (`vulkaninfo --summary` prints the device). Without it the engine falls back to CPU and a
run takes several times longer.

```bash
# uv, the Python toolchain (no root, installs to ~/.local/bin)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or `~/.zshrc`): systemd units that run
`uv` need it too.

---

## 1. The application

```bash
git clone https://github.com/stefare90/jobcaliber ~/jobcaliber
cd ~/jobcaliber
uv sync --frozen            # exact versions from uv.lock
```

**Check**

```bash
uv run pytest -q                 # must end with "N passed"
uv run jobcaliber --help         # run | status | db | jobs
```

---

## 2. The scoring engine

The default engine is **rizzo-flow**: a 4B decision model served by llama.cpp, Apache-2.0, no API
key, nothing leaves the machine.

```bash
git clone https://github.com/Rizzo-AI-Academy/rizzo-flow ~/rizzo-flow
cd ~/rizzo-flow
uv sync --locked
uv run rizzo download --quant q4_k_m     # ~2.5 GB of weights + the llama.cpp runtime
uv run rizzo devices                     # which device `--device auto` will pick
```

Start it once by hand to see the log:

```bash
uv run rizzo serve --port 8017 --device auto --quant q4_k_m
```

**Check** (in another terminal)

```bash
curl -s http://127.0.0.1:8017/v1/models     # a JSON list; the serve log says the device it chose
```

> **Sizes and speed.** `q4_k_m` (2.5 GB) is the default here; `q8_0` (4.4 GB) is the upstream
> default and, at 4B, ties the Q4 on their own benchmark while taking ~1.8x the bandwidth. On a
> CPU-only machine without an iGPU, expect 20–40 s per offer with either quant; see
> [`docs/OPERATIONS.md`](OPERATIONS.md#engines) for what to do about it.

If you prefer not to run a model locally, skip this step and configure an OpenAI-compatible
engine instead (see step 4 and [`config/README.md`](../config/README.md)).

---

## 3. Configuration

```bash
cd ~/jobcaliber
mkdir -p config
cp config/profile.example.yaml config/profile.yaml      # what to look for + the criteria
cp config/settings.example.yaml config/settings.yaml    # scraping, schedule, notifications, ai
cp .env.example .env && chmod 600 .env
```

Edit `config/profile.yaml` first — it is the only file you *must* touch:

1. `search.titles` — the job titles you want, as the boards spell them.
2. `search.on_site_locations` / `search.remote_locations` — board-ready strings
   (`"Sardinia, Italy"`, `"Italy"`, `"Berlin, Germany"`). Multi-line values are allowed.
3. `search.exclude` — the phrases that mean "not for me" (used by the `applicable` criterion).
4. `criteria` — the questions you want answered, each with thresholds or a gate,
   and its `missing` marker.

Then `config/settings.yaml`:

1. `schedule.timezone` — **required**, an IANA name (`Europe/Rome`, `UTC`, …).
2. `schedule.scrape_times` — when the daily runs happen, in that timezone.
3. `scraping.boards` and `scraping.board_max_results` — which boards and how deep.
4. `notifications.telegram` — leave `enabled: false` for now (step 5).
5. `ai.roles.scorer` — must name one of `ai.engines` entries; the default is `rizzo`.

**Check** — the loader validates everything and fails fast with the exact key:

```bash
uv run jobcaliber db version     # "new database (will be created at vN on first use)"
uv run jobcaliber status         # "no runs yet"
```

A wrong `schedule.timezone`, a criterion without thresholds or a gate, or an unresolved
`{{placeholder}}` stops here with a message — that is the intended behaviour.

The complete reference of both files is in [`config/README.md`](../config/README.md).

---

## 4. First run

Start small, then let it be:

```bash
uv run jobcaliber run --limit 5 --max-queries 1     # ~1 minute: 1 query x 2 boards + 5 scores
```

**Check**

```bash
uv run jobcaliber status
# run 1 · <local time> · ok · trigger cli · engine rizzo · config_v 1
# fetched <N> · usable <N> · new <N> · scored 5 · <N>s
```

If it says `EngineUnreachable`, the engine from step 2 is not running: start it, then repeat.

A full pass is `uv run jobcaliber run` (no flags): ~30 min of fetching plus ~6 s per new offer.
On a new database that first full pass is the expensive one; after it, only new offers are scored.

---

## 5. Telegram (optional)

1. In Telegram, write to **@BotFather** → `/newbot` → choose a name and a username ending in
   `bot`. It answers with a **token** (`123456789:AAH…`).
2. Open a chat with your new bot and press **Start** (a bot cannot write to you first).
3. Read the chat id:

   ```bash
   set -a; . ./.env; set +a
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" \
     | grep -o '"chat":{"id":[-0-9]*' | head -1
   ```

4. Put the token in `.env` (`TELEGRAM_BOT_TOKEN=…`) and the id in `config/settings.yaml`:

   ```yaml
   notifications:
     base_url: http://192.168.1.28:8000     # what the phone can reach (see step 7)
     telegram: {enabled: true, chat_id: "657083271"}
   ```

**Check** — the next run that finds a `pass` offer sends one message. To test without waiting for
a run:

```bash
uv run python - <<'PY'
from pathlib import Path
from jobcaliber.bootstrap import build_context
ctx = build_context(Path("."))
rows = [r for r in ctx.store.new_notifiable() if r.decision == "pass"]
print("rows:", len(rows), "|", ctx.notifier.send(rows, None) or "sent")
PY
```

The message contains every `pass` offer of the run, the link to each ad and a link to the filtered
list. Offers you marked (*Applied* / *Will apply* / *Not interested*) are never sent.

---

## 6. systemd units

Three units, all in the **user** manager (no root), all with `Restart=always` so the machine comes
back up working.

```bash
cd ~/jobcaliber
mkdir -p ~/.config/systemd/user
cp deploy/jobcaliber-worker.service deploy/jobcaliber-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jobcaliber-worker jobcaliber-web
loginctl enable-linger "$USER"          # keep them running after logout and at boot
```

The engine is a **system** unit, named after what it runs (`rizzo`), and it is **not enabled**: the
worker starts it on demand (and the model host's own watchdog powers the machine off if nobody
shuts it down).

```bash
sudo cp deploy/rizzo.service.example /etc/systemd/system/rizzo.service
sudo systemctl daemon-reload
sudo systemctl start rizzo          # once, to check it answers
```

**Check**

```bash
systemctl --user --no-pager status jobcaliber-worker jobcaliber-web | grep -E "●|Active"
systemctl status rizzo --no-pager | head -3
journalctl --user -u jobcaliber-worker -n 20 --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz     # 200
```

The worker logs one line per tick only when something happens (a run, a reload). A quiet log is a
healthy log: it means nothing is due.

---

## 7. Access from the phone (optional)

The web unit already binds `0.0.0.0`; what is missing is the firewall. On a machine with
`firewalld` and a `192.168.1.0/24` LAN:

```bash
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" \
  port port="8000" protocol="tcp" accept' --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-rich-rules

ip route get 1.1.1.1 | awk '{print $7}'    # the LAN address to type on the phone
```

`http://<lan-ip>:8000` works on any device on that network. For a name instead of an IP, either
use the mDNS name (`http://<hostname>.local:8000`, native on iOS/macOS; Android is unreliable) or
add a line to `/etc/avahi/hosts`:

```bash
echo "192.168.1.28 jobcaliber.local" | sudo tee -a /etc/avahi/hosts
sudo systemctl restart avahi-daemon
```

> **There is no authentication.** Anyone on that network can read the offers, mark them and press
> *Run now*. Keep the rule narrow, or put Tailscale in front (it also gives you HTTPS and a
> stable name outside the house). Do not expose the port to the internet.

---

## 8. Final checklist

```bash
curl -s http://127.0.0.1:8017/v1/models > /dev/null      && echo "engine ok"
curl -s -o /dev/null -w 'web %{http_code}\n' http://127.0.0.1:8000/healthz
systemctl --user is-active jobcaliber-worker jobcaliber-web
systemctl is-active rizzo
uv run jobcaliber status | head -3
uv run jobcaliber db check
uv run python -c "from pathlib import Path; from jobcaliber.bootstrap import build_context; \
print(build_context(Path('.')).config.schedule.timezone)"
```

Expected: `engine ok`, `web 200`, three times `active`, a run line, `schema matches schema.sql`,
and your timezone.

When everything is green, the machine can be left alone: the worker runs the configured slots,
the web shows the results, and Telegram tells you when a new offer is worth opening.

---

## Upgrading

```bash
cd ~/jobcaliber
git pull
uv sync --frozen
uv run jobcaliber db check              # if it complains, read the message: it names the command
uv run jobcaliber db migrate --dry-run  # then, if it lists steps:
uv run jobcaliber db migrate
systemctl --user restart jobcaliber-web jobcaliber-worker
```

The database refuses to open on a schema mismatch instead of guessing; a migration always takes a
backup first (`data/jobs.db.bak-vN`). Nothing else is needed: the config files are yours and are
never overwritten by an upgrade.

## Uninstalling

```bash
systemctl --user disable --now jobcaliber-web jobcaliber-worker
sudo systemctl disable --now rizzo 2>/dev/null
rm -f ~/.config/systemd/user/jobcaliber-*.service
rm -rf ~/jobcaliber ~/rizzo-flow
```

`data/jobs.db` lives inside the project folder: copy it somewhere before deleting the directory if
you want to keep the history.
