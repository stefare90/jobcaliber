# Spike 04 — model host: can the worker wake the machine that runs the model?

**Question:** can a small always-on machine (the *controller*, running web + worker + database)
power on the more powerful machine that only serves the scoring model (the *model host*), start the
engine on it, use it over the LAN, and shut it down again — reliably enough to run unattended once a
day?

**Why it decides the project.** If this works, the database, the web and the fetch stay on one
machine (the controller), and only the model lives on the host: no database over the network, no
API to invent, and the quality of the 4B engine is kept. If it does not work (no Wake-on-LAN, no
cable, Wi-Fi only), the fallback is a paid API engine — a different product trade-off.

Everything below must **run end-to-end and report real numbers**, not be assumed.

---

## Already verified on the development machine (2026-10-24)

| check | result |
|---|---|
| the machine has a free Ethernet interface | `enp5s0`, MAC `34:5a:60:a2:87:9c`, currently `DOWN` (the LAN is on Wi-Fi) |
| `rizzo serve` can listen on all interfaces | `--host 0.0.0.0` works: `ss -ltn` shows `0.0.0.0:8017`, `curl http://192.168.1.28:8017/v1/models` → 200 |
| the magic packet payload | 102 bytes: `6×0xFF` + MAC repeated 16 times, byte-identical to the expectation (tested against a local UDP listener) |
| Wake-on-LAN support of the NIC | **not yet known** — needs `sudo ethtool enp5s0` (see step 1) |
| whether an external host may reach `:8017` | **not yet known** — loopback to the LAN address does not prove the firewall rule |

---

## Checklist (run when the two machines are cabled together)

Each step has an expected output. **Stop at the first failure**: the design depends on all of them.

### 1. Wake-on-LAN capability of the model host

On the model host:

```bash
sudo ethtool enp5s0 | grep -A1 "Supports Wake-on"     # expect: Supports Wake-on: pumbg
sudo ethtool enp5s0 | grep "Wake-on"                  # expect: Wake-on: d  (disabled)
sudo ethtool -s enp5s0 wol g                          # enable magic-packet wake
sudo ethtool enp5s0 | grep "Wake-on"                  # expect: Wake-on: g
```

Persist it (so it survives a reboot) with NetworkManager:

```bash
nmcli con modify "<ethernet-profile>" 802-3-ethernet.wake-on-lan magic
```

and in the **BIOS**: Wake-on-LAN / "Power on by PCIe" enabled, **ErP/EuP disabled** (ErP cuts the
standby power the NIC needs while the machine is off).

**Pass:** `Wake-on: g` after a reboot, and the NIC LED stays lit while the machine is powered off.

### 2. Direct cable, static addresses, no gateway

Both machines get an address on the point-to-point link and **no default route there** (internet
keeps flowing through Wi-Fi):

```bash
# model host (.2), controller (.1)
nmcli con add type ethernet ifname enp5s0 con-name jobcaliber-link \
  ipv4.method manual ipv4.addresses 10.10.0.2/24 ipv4.never-default yes ipv6.method disabled
nmcli con up jobcaliber-link
ip route get 1.1.1.1          # expect the Wi-Fi interface, not the cable
```

**Pass:** `ping -c3 10.10.0.1` from the host and `ping -c3 10.10.0.2` from the controller, **and**
on both machines `ip route get 1.1.1.1` still names the Wi-Fi interface.

### 3. The engine over the cable, and the controller's firewall

On the model host:

```bash
cd ~/rizzo-flow && uv run rizzo serve --host 0.0.0.0 --port 8017 --device auto --quant q4_k_m
```

On the controller:

```bash
curl -s http://10.10.0.2:8017/v1/models | head -c 200      # a JSON list of models
```

If it times out, open the port **only to the controller** (`firewalld` on the host):

```bash
sudo firewall-cmd --add-rich-rule='rule family="ipv4" source address="10.10.0.1/32" \
  port port="8017" protocol="tcp" accept' --permanent
sudo firewall-cmd --reload
```

**Pass:** the JSON arrives from the controller. **Expected latency:** one scoring call should add
well under a millisecond over a direct gigabit link (measure with `curl -w '%{time_total}\n'` on a
real `/v1/systemone` request: expect ~the same as local).

### 4. SSH with a forced command (start and stop the engine)

On the model host, create a key for the controller and restrict it in `~/.ssh/authorized_keys`:

```
command="sudo /usr/bin/systemctl start rizzo",no-port-forwarding,no-pty,no-agent-forwarding ssh-ed25519 AAAA… jobcaliber@controller
```

A second key line does the same for `poweroff`, so the two capabilities stay separate. Passwordless
sudo for exactly those two commands:

```
stefare ALL=(root) NOPASSWD: /usr/bin/systemctl start rizzo
stefare ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff
```

The engine becomes a **system** unit (no `enable`: it is started on demand):

```bash
sudo cp deploy/rizzo.service.example /etc/systemd/system/rizzo.service
sudo systemctl daemon-reload
sudo systemctl start rizzo          # not enabled: started on demand by the controller
```

**Pass:** from the controller, `ssh host` starts the engine (`curl` then succeeds) and a second
`ssh` key powers the machine off.

### 5. Wake from power-off (the one that decides)

```bash
# on the controller, with the model host powered off
wakeonlan -i 10.10.0.255 34:5a:60:a2:87:9c          # or the project's magic_packet()
time ssh host true                                  # stopwatch: OS up
time curl -s http://10.10.0.2:8017/v1/models        # stopwatch: engine answering
```

**Pass, and record the numbers:** machine awake after ~20–60 s, engine answering ~10–60 s later
(model load on the iGPU). Anything beyond ~3 minutes makes `wait_s: 150` too small and the design
marginal.

### 6. Shutdown, and the watchdog

From the controller, after the run:

```bash
ssh host 'sudo systemctl poweroff'      # ordered shutdown, llama.cpp released cleanly
```

**Pass:** the machine powers off; the NIC LED stays on (so the next wake is possible); a second
wake works.

---

## Decision gate

| outcome | decision |
|---|---|
| steps 1–6 pass, wake ≤ 3 min | implement the `model_host` feature (wake on demand, engine started/stopped over SSH, shutdown at the end) |
| WoL works but the boot is slower | keep the design, raise `wait_s`; the probe stays **before** the fetch (a rerun re-fetches anyway, so failing early is cheaper) |
| WoL impossible (Wi-Fi only, or BIOS without the option) | **fall back to a paid API engine** on the controller; the mini-PC then needs no second machine |

## Numbers to write down

- wake time (power-off → SSH answering): ____ s
- engine ready (SSH → `/v1/models`): ____ s
- scoring latency over the cable vs localhost, on the same posting: ____ s / ____ s
- after a wake, the first request of the run: ____ s (model load included?)
