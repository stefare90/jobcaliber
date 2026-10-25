# `deploy/` — the units

Two files are jobcaliber's own units. The third is a **reference for the model host**, a different
machine that exposes a model API and has no reason to know that jobcaliber exists.

| File | Runs on | Process | Listens on |
|---|---|---|---|
| `jobcaliber-worker.service` | controller | schedule + run queue | — |
| `jobcaliber-web.service` | controller | the web app | `0.0.0.0:8000` (firewall-restricted) |
| `rizzo.service.example` | **model host** | the local scoring engine | `0.0.0.0:8017` |

The dependency arrow points one way: the controller knows the name of the service it starts
(`sudo systemctl start rizzo`); the model host knows nothing about jobcaliber.

## Install

On the **controller** (web + worker, user units):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/jobcaliber-worker.service deploy/jobcaliber-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jobcaliber-worker jobcaliber-web
loginctl enable-linger "$USER"          # keep them running after logout and at boot
```

On the **model host** (the engine, a *system* unit, **not enabled** — it starts on request):

```bash
sudo cp deploy/rizzo.service.example /etc/systemd/system/rizzo.service
sudo systemctl daemon-reload
sudo systemctl start rizzo              # and `sudo systemctl stop rizzo`
```

The units assume the project in `~/jobcaliber` and the engine in `~/rizzo-flow`; edit
`WorkingDirectory` and `ExecStart` if yours are elsewhere.

## Verify

```bash
systemctl --user --no-pager status jobcaliber-worker jobcaliber-web | grep -E "●|Active"
journalctl --user -u jobcaliber-worker -n 20 --no-pager
curl -s -o /dev/null -w 'web %{http_code}\n' http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8017/v1/models > /dev/null && echo "engine ok"     # on the model host
```

## Notes

- `EnvironmentFile=-%h/.config/jobcaliber/env` is optional (`-`): a missing file is not fatal. Use
  it for secrets you prefer not to keep in the project's `.env`.
- `Restart=always` is deliberate: the worker must survive a reboot, and the engine must come back
  after an OOM kill (llama.cpp re-loads the weights, ~5 s).
- The worker is single-threaded and claims runs atomically, so **only one worker** may run. A
  second copy would idle on the same queue rather than duplicate work, but there is no reason for
  it.
- The web unit binds `0.0.0.0` so a phone on the LAN can reach it. There is **no authentication**:
  restrict the port to your subnet with the firewall (see `docs/INSTALL.md`, step 7).
