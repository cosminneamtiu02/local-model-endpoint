# Ollama Launchd Agent

This document describes the user-scope `launchd` agent that keeps the Ollama
daemon running on the LIP Mac Mini, the env vars it bakes in, and the
operator commands for installing, uninstalling, checking, and customizing it.

It is the operator-facing companion to LIP-E005-F003.

## What this is

`infra/launchd/com.lip.ollama.plist.tmpl` is the canonical `launchd` config
template for the always-on Ollama daemon that LIP's FastAPI service talks to
over HTTP at `http://localhost:11434`. The template's ``__HOME__`` placeholder
is substituted with `$HOME` at install time (launchd does not expand env vars
in plists), then the rendered file is installed at
`~/Library/LaunchAgents/com.lip.ollama.plist`. The plist:

- runs `ollama serve` at user login (`RunAtLoad=true`),
- restarts Ollama if it crashes (`KeepAlive=true`),
- runs as a low-priority background process (`ProcessType=Background`),
- writes stdout/stderr to `~/Library/Logs/ollama/`,
- and presets the five env vars that calibrate Ollama for LIP's workload on the
  16 GB M4 Mac Mini base.

Why a launchd agent at all: launching Ollama from the GUI app or from
`ollama serve` in a terminal leaves the daemon tied to that UI session. The
moment the dock icon closes or the terminal exits, Ollama goes down and the
next LIP request sees `connection_refused`. The launchd agent decouples the
daemon from any interactive session — it survives terminal closures, GUI app
exits, and idle macOS sessions, and it restarts on crash. LIP's FastAPI side
stays on-demand; Ollama is the always-on substrate.

The plist installs to `~/Library/LaunchAgents/com.lip.ollama.plist` and is
bootstrapped under the `gui/$(id -u)` domain — the right scope for "starts
when Cosmin logs in," not system-wide and not requiring root.

## Install

Prerequisite: Ollama is already installed on the Mac. The canonical way is
`brew install ollama` on Apple Silicon (binary lands at
`/opt/homebrew/bin/ollama`); see "Customizing for non-Homebrew installs"
below if your binary is elsewhere.

```bash
task ollama:install
```

Behind the scenes this:

1. Creates `~/Library/Logs/ollama/` if missing (so the plist's
   `StandardOutPath`/`StandardErrorPath` have a destination).
2. Creates `~/Library/LaunchAgents/` if missing.
3. Refuses to run as root (LaunchAgent must be in the user domain).
4. Substitutes `__HOME__` with `$HOME` and writes the rendered plist to
   `~/Library/LaunchAgents/com.lip.ollama.plist` via `sed`.
4. Bootstraps the agent into the GUI session domain:
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lip.ollama.plist`.

After `task ollama:install`, Ollama is running and `task ollama:status` should
report `state = running`. An HTTP probe to `http://localhost:11434/api/tags`
should return 200 within ~2 seconds.

The install task is **not** idempotent: re-running it after the agent is
already loaded will fail at the `bootstrap` step with a non-zero error such
as `Bootstrap failed: 37: Operation already in progress` (or `5:
Input/output error` on older macOS). The clean reload pattern is
`task ollama:uninstall && task ollama:install`. Note that `launchctl
kickstart -k gui/$(id -u)/com.lip.ollama` only restarts the *running
daemon* using the already-bootstrapped (in-memory) plist — it does **not**
re-read the on-disk plist, so it cannot pick up plist edits. Use it to
recycle the daemon (e.g. after `brew upgrade ollama`); use
uninstall+install to apply plist changes.

## Uninstall

```bash
task ollama:uninstall
```

This boots the agent out of the GUI domain and deletes the installed plist.
After it runs, `launchctl print gui/$(id -u)/com.lip.ollama` returns "could
not find service" — clean removal.

## Status check

```bash
task ollama:status
```

This runs `launchctl print gui/$(id -u)/com.lip.ollama` and prints the
human-readable launchd state, including the resolved environment variables
for the agent. Use this to verify after install that the five LIP env vars
made it through (look for the `environment = { ... }` block in the output).

`task ollama:status` reports launchd state, **not** Ollama-daemon liveness.
For a liveness probe, hit `http://localhost:11434/api/tags` directly.

## Env vars explained

The plist sets five Ollama env vars that calibrate the daemon for LIP's
single-developer, single-machine, single-model workload on a 16 GB Mini:

| Env var | Value | Why this value |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `300s` | Unloads the model from RAM 300 s (= 5 min) after the last request. **Matches Ollama's current upstream default** (`5m`); pinning explicitly here is defense-in-depth against upstream default drift. Pairs with LIP's 10-minute idle FastAPI shutdown — by the time LIP exits and the next consumer wake-up arrives, Ollama has unloaded the model and reloads it on demand, freeing RAM for desktop work in between. |
| `OLLAMA_NUM_PARALLEL` | `1` | Pins Ollama's internal parallel-request slots to 1. **Matches Ollama's current upstream default**; pinned explicitly as defense-in-depth for LIP's `asyncio.Semaphore(1)` — if the service-layer serialization ever breaks, or upstream raises the default, Ollama still won't run two streams concurrently. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Caps resident models at 1 (Ollama's default `0` means "auto-derive from VRAM," which on a 16 GB Mini may pick 2–3 and OOM). Enforces the 16 GB memory envelope: at most one model resident at a time. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enables FlashAttention (Ollama's default is off). Cuts attention-step memory and is required (alongside `OLLAMA_KV_CACHE_TYPE`) for the 128K-context Gemma 4 E2B not to OOM the Mini. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Quantizes the KV cache to 8-bit (Ollama's default is `f16`). Significantly reduces KV-cache RAM for long contexts on the 16 GB Mini. |

LIP intentionally does **not** set `OLLAMA_HOST` — Ollama's default
`http://127.0.0.1:11434` keeps the daemon bound to loopback only, which is
the right posture for the local-network-only trust model. Setting
`OLLAMA_HOST=0.0.0.0:11434` would expose the daemon to the LAN and is not
something v1 wants.

Calibrated memory footprints from the disambiguated idea
(`docs/disambigued-idea.md`): idle Ollama ≈ <200 MB, active with Gemma 4
E2B loaded ≈ 7.5 GB. These are operator-observed targets via Activity
Monitor / `ps`, not pytest-asserted (see `LIP-E005-F003`'s "Out of scope"
section for why memory assertions aren't in CI).

## Customizing for non-Homebrew installs

The plist template hardcodes `/opt/homebrew/bin/ollama` as the path to the
Ollama binary — the Apple Silicon Homebrew default. If your Ollama lives
elsewhere, edit the first `<string>` entry in the `ProgramArguments` array
of `infra/launchd/com.lip.ollama.plist.tmpl`:

```xml
<key>ProgramArguments</key>
<array>
    <string>/path/to/your/ollama</string>
    <string>serve</string>
</array>
```

Common alternatives:

- **Intel Mac with Homebrew**: `/usr/local/bin/ollama`
- **Manual install / one-off**: `~/bin/ollama` (use absolute path; `~`
  doesn't expand in plists).
- **`asdf` / `mise` shim**: point at the resolved real path
  (`asdf which ollama`), not the shim — launchd doesn't run your shell rc
  files, so PATH-based shims won't work.

After editing, reload with:

```bash
task ollama:uninstall
task ollama:install
```

The same procedure applies if you want to redirect the log paths
(`StandardOutPath`/`StandardErrorPath`) — those hardcode
`/Users/cosminneamtiu/Library/Logs/ollama/` because this plist ships as the
deployment artifact for *this* machine. Edit those two `<string>` values to
your home directory's `Logs/ollama/` if you adopt this repo on a different
account.

> ⚠️ **Heads-up on log-path edits.** `task ollama:install` always runs
> `mkdir -p ~/Library/Logs/ollama` regardless of what `StandardOutPath` /
> `StandardErrorPath` say in the plist. If you point the plist at a
> different log directory, also edit the install task's `mkdir` line in
> `Taskfile.yml` (or pre-create the target directory manually) — otherwise
> launchd silently drops stdout/stderr because the file paths don't exist,
> and Ollama runs but its logs vanish.

To validate your edits before reinstalling:

```bash
task check:plist
```

This is also wired into `task check`, so CI catches a malformed plist before
it reaches `launchctl bootstrap`.

## Troubleshooting

- **`bootstrap` fails with a non-zero exit (e.g. `Bootstrap failed: 37:
  Operation already in progress`)** — the agent is already installed. The
  exact message varies across macOS versions; the symptom is what matters.
  Run `task ollama:uninstall` first, then `task ollama:install`.
- **`bootstrap` fails with `Bootstrap failed: 5: Input/output error`** —
  usually a malformed plist. Run `plutil -lint
  infra/launchd/com.lip.ollama.plist.tmpl` (or `task check:plist`) to find
  the schema problem before re-trying.
- **You edited the plist and the new env vars don't show up in `task
  ollama:status`** — `launchctl kickstart -k` does **not** re-read the
  on-disk plist; it only restarts the daemon under the already-bootstrapped
  in-memory plist. Plist edits require `task ollama:uninstall && task
  ollama:install` (or `launchctl bootout` + `bootstrap` directly).
- **`task ollama:status` shows the agent loaded but Ollama isn't responding
  on `localhost:11434`** — check `~/Library/Logs/ollama/stderr.log` for the
  daemon's own error output. Common causes: the binary path in the plist is
  wrong, or another process already bound port 11434.
- **You can't stop the daemon with `launchctl kill SIGTERM …`** — `KeepAlive=true`
  is set, so launchd respawns the process after every signal-induced exit
  (subject to the ~10 s `ThrottleInterval` default). To actually stop the
  daemon, use `task ollama:uninstall` (or `launchctl bootout
  gui/$(id -u)/com.lip.ollama`) — that unloads the agent definition itself,
  so launchd no longer respawns.
- **Ollama upgrade via `brew upgrade ollama`** — the binary path doesn't
  change (`/opt/homebrew/bin/ollama` is a stable shim on Apple Silicon
  Homebrew), so no plist edit is needed. Restart the daemon so the new
  binary is loaded: `launchctl kickstart -k gui/$(id -u)/com.lip.ollama`
  (this is the one case where `kickstart -k` is the right tool).
