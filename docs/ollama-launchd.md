# Ollama launchd agent

This document describes the user-scope `launchd` agent that keeps the Ollama
daemon running on the LIP Mac Mini, the env vars it bakes in, and the
operator commands for installing, uninstalling, checking, and customizing it.

It is the operator-facing companion to LIP-E005-F003.

## What this is

`infra/launchd/com.lip.ollama.plist` is the canonical `launchd` config for the
always-on Ollama daemon that LIP's FastAPI service talks to over HTTP at
`http://localhost:11434`. The plist:

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
3. Copies `infra/launchd/com.lip.ollama.plist` to
   `~/Library/LaunchAgents/com.lip.ollama.plist`.
4. Bootstraps the agent into the GUI session domain:
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lip.ollama.plist`.

After `task ollama:install`, Ollama is running and `task ollama:status` should
report `state = running`. An HTTP probe to `http://localhost:11434/api/tags`
should return 200 within ~2 seconds.

The install task is **not** idempotent: re-running it after the agent is
already loaded will fail at the `bootstrap` step with "Service already
loaded." The clean reload pattern is `task ollama:uninstall && task
ollama:install`. To restart in place after editing the plist, prefer
`launchctl kickstart -k gui/$(id -u)/com.lip.ollama`.

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
| `OLLAMA_KEEP_ALIVE` | `300s` | Unloads the model from RAM after 5 minutes of inactivity. Pairs with LIP's 10-minute idle FastAPI shutdown — by the time LIP exits and the next consumer wake-up arrives, Ollama has unloaded the model and reloads it on demand, freeing RAM for desktop work in between. |
| `OLLAMA_NUM_PARALLEL` | `1` | Disables Ollama's internal parallel request slots. Defense in depth for LIP's `asyncio.Semaphore(1)` — if the service-layer serialization ever breaks, Ollama still won't run two streams concurrently. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Enforces the 16 GB memory envelope: at most one model resident at a time. Two simultaneously-loaded models won't fit. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enables FlashAttention. Cuts attention-step memory and is required (alongside `OLLAMA_KV_CACHE_TYPE`) for the 128K-context Gemma 4 E2B not to OOM the Mini. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Quantizes the KV cache to 8-bit. Significantly reduces KV-cache RAM for long contexts on the 16 GB Mini. |

Calibrated memory footprints from the disambiguated idea
(`docs/disambigued-idea.md`): idle Ollama ≈ <200 MB, active with Gemma 4
E2B loaded ≈ 7.5 GB. These are operator-observed targets via Activity
Monitor / `ps`, not pytest-asserted (see `LIP-E005-F003`'s "Out of scope"
section for why memory assertions aren't in CI).

## Customizing for non-Homebrew installs

The plist hardcodes `/opt/homebrew/bin/ollama` as the path to the Ollama
binary — the Apple Silicon Homebrew default. If your Ollama lives elsewhere,
edit the first `<string>` entry in the `ProgramArguments` array of
`infra/launchd/com.lip.ollama.plist`:

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

To validate your edits before reinstalling:

```bash
task check:plist
```

This is also wired into `task check`, so CI catches a malformed plist before
it reaches `launchctl bootstrap`.

## Troubleshooting

- **`bootstrap` fails with "Service already loaded"** — the agent is already
  installed. Run `task ollama:uninstall` first, then `task ollama:install`.
  Or skip the unload step and just `launchctl kickstart -k
  gui/$(id -u)/com.lip.ollama` to restart the agent in place.
- **`bootstrap` fails with "Bootstrap failed: 5: Input/output error"** —
  usually a malformed plist. Run `plutil -lint
  infra/launchd/com.lip.ollama.plist` (or `task check:plist`) to find the
  schema problem before re-trying.
- **`task ollama:status` shows the agent loaded but Ollama isn't responding
  on `localhost:11434`** — check `~/Library/Logs/ollama/stderr.log` for the
  daemon's own error output. Common causes: the binary path in the plist is
  wrong, or another process already bound port 11434.
- **Ollama upgrade via `brew upgrade ollama`** — the binary path doesn't
  change (`/opt/homebrew/bin/ollama` is a stable shim on Apple Silicon
  Homebrew). Restart the agent so the new binary is loaded:
  `launchctl kickstart -k gui/$(id -u)/com.lip.ollama`.
