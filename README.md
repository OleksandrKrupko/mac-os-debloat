# mac-os-debloat

**Debloat your Mac from the terminal. Zero dependencies. Zero install.**

Interactive console util to disable 269 non-essential macOS launchd services. Reclaims ~1.5-2 GB RAM and a chunk of CPU for whatever heavy work you're actually doing. Persistent across reboot. Fully reversible. Built for macOS Tahoe 26.x on Apple Silicon.

**No SIP disable required** — works with System Integrity Protection fully on, via Apple's supported `launchctl disable`. That covers ~90-95% of the bloat with zero security tradeoff; squeezing the last few daemons means turning SIP off permanently, which isn't worth it for most people. It also validates every service against your actual system at launch, so it never acts on a label that doesn't exist on your macOS build.

```bash
npx -y @oleksandr_krupko/mac-os-debloat
```

Or via curl:

```bash
curl -fsSL https://raw.githubusercontent.com/OleksandrKrupko/mac-os-debloat/main/debloat | python3
```

Or via Homebrew:

```bash
brew install OleksandrKrupko/debloat/debloat && debloat
```

All three methods need `python3` — preinstalled with the Xcode Command Line Tools (`xcode-select --install` if it's missing). No SIP disable required. The curl one-liner pipes the script to `python3`, so it reopens `/dev/tty` for the interactive keys; if you have no terminal attached, use the non-interactive flags below or the `npx` launcher.

## Commands

Runs the interactive TUI by default. Non-interactive flags for scripting and quick recovery:

```bash
debloat                 # interactive TUI (default)
debloat --status        # disabled/enabled counts, spotlight, reclaimable RAM
debloat --audit         # list any embedded labels not present on your macOS build
debloat --disable-all   # disable every non-essential service (prompts sudo)
debloat --enable-all    # re-enable everything — the panic button
debloat --restore       # revert to the state before your last apply
debloat --dry-run       # with --disable-all/--enable-all: preview, apply nothing
debloat --status --json # machine-readable status
```

`--status`, `--audit`, and `--dry-run` need no sudo — reading launchd state is unprivileged. Every apply first snapshots your current state to `~/.mac-os-debloat/latest.json`, so `--restore` always brings you back. If anything feels off, `debloat --enable-all` turns it all back on.

## Screenshot

```
mac-os-debloat  —  space=toggle  x=sec-toggle  s/S=sec-off/on  [/]=jump  a/n=all/none  p=spotlight  enter=apply  q=quit
pending: 4   (spotlight: ON)   (checked = enabled/running)

── Siri / voice assistant ──────────────────────────────────────────────────
 *[ ]  com.apple.assistantd                          Siri core
 *[ ]  com.apple.Siri.agent                          Siri agent
  [ ]  com.apple.SiriTTSTrainingAgent                Siri voice training
  [ ]  com.apple.siriinferenced                      on-device Siri inference
 *[ ]  com.apple.siriknowledged                      Siri knowledge graph
  [ ]  com.apple.assistant_cdmd                      Siri continuous dialog manager
  [✓]  com.apple.parsecd                             Siri/Spotlight suggestions backend
  [✓]  com.apple.parsec-fbf                          Siri Suggestions feedback
 *[ ]  com.apple.intelligencecontextd                Apple Intelligence context runtime
  [✓]  com.apple.intelligenceplatformd               Apple Intelligence platform

── Apple Intelligence (Tahoe) ────────────────────────────────────────────── ↓
  [✓]  com.apple.mlruntimed                          ML runtime
► [✓]  com.apple.privatecloudcomputed                Private Cloud Compute (AI cloud offload)
  [✓]  com.apple.modelmanagerd                       AI model manager / downloads
  [✓]  com.apple.naturallanguaged                    NaturalLanguage framework daemon
  [✓]  com.apple.generativeexperiencesd              Writing Tools / generative AI
  [✓]  com.apple.contextstored                       context store (>30GB memory leak)
```

<details>
<summary><b>What it disables</b></summary>

269 labels across 69 sections. Highlights:

- Siri / voice assistant (12)
- Apple Intelligence — Tahoe (10), incl. `contextstored` (known >30 GB memory leak) and `privatecloudcomputed`
- More AI / Apple Intelligence (11) — CoreSpotlight semantic, call intelligence, intelligence flow / tasks
- Diagnostics extras (30) — all telemetry to Apple
- Apple Music Player (AMP) suite (5), Apple Music / iTunes / Media streaming (7)
- Safari + Safari extras (7) — for non-Safari users
- Game Center, Game controllers, Game policy (7)
- Family / Parental controls (8)
- Beta program enrollment (6)
- iMessage / FaceTime / phone relay (10)
- Apple Mail / Calendar / Contacts / Reminders + AddressBook (7)
- Continuity / AirPlay / Sidecar / Continuity Capture (~8)
- Maps, Apple Books, Apple TV+, Stocks/News/Weather/Sports
- App Store + Apple ID + Apple Pay + SSO
- iCloud Drive / Keychain Circle / Notifications
- Print (no printer), Touch Bar (M4 has none), bridgeOS (Apple Silicon)
- Xcode / iOS dev stack (FE/BE dev, no mobile)
- Telemetry + Apple ads + Proactive / predictive + News / Stocks / Weather

Full curated list with per-label comments lives inside the script (`EMBEDDED_LABELS`).

</details>

<details>
<summary><b>Keys</b></summary>

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | navigate |
| `PgUp` / `PgDn` | jump 10 |
| `[` / `]` | jump to prev / next section |
| `space` | toggle current item |
| `x` | toggle whole section under cursor |
| `s` / `S` | uncheck / check whole section |
| `a` / `n` | check / uncheck all |
| `p` | toggle Spotlight indexing on root volume |
| `enter` | apply changes (prompts sudo) |
| `r` | reload state from system |
| `q` / `esc` | quit |

`[✓]` = enabled · `[ ]` = disabled · ` *` = unsaved change

</details>

<details>
<summary><b>Persistence</b></summary>

Uses `launchctl disable` — writes to `/var/db/com.apple.xpc.launchd/disabled.plist`.

- Survives reboot
- Wiped by macOS major upgrades (26.3 → 26.4 etc) — re-run after upgrade
- `system/` disables affect all users · `gui/$UID` disables only current user
- Multi-user: run once per account

</details>

<details>
<summary><b>Troubleshooting</b></summary>

**`Boot-out failed: 150: Operation not permitted while System Integrity Protection is engaged`** (e.g. on `com.apple.followupd`)
Expected for a handful of daemons Apple protects even from a live `bootout`, and not a reason to disable SIP. The persistent half — `launchctl disable` — already succeeded and takes effect on your next login/reboot; the failed `bootout` only means that one running process couldn't be killed immediately. Run `debloat --status` after a reboot to confirm it's disabled.

</details>

<details>
<summary><b>Customizing</b></summary>

Drop a `labels.txt` next to the script — it overrides embedded list.

```
# === Your section ===
com.apple.something                # what it does, what breaks
```

</details>

<details>
<summary><b>Don't disable these</b></summary>

These will break the system. Not in default list, but if you add manually:

- `com.apple.WindowServer`, `controlcenter`, `notificationcenterui`, `Finder`, `Dock`, `SystemUIServer` — UI dies
- `com.apple.coreaudiod` — sound dies
- `com.apple.accountsd`, `syspolicyd`, `securityd`, `trustd` — auth / codesign break
- `com.apple.mds*`, `corespotlightd` — use `mdutil -a -i off` instead
- `com.apple.softwareupdated` — kills security updates
- `com.apple.XprotectService` — kills malware scanning
- `com.apple.CoreLocationAgent`, `searchpartyd` — Find My breaks

</details>

<details>
<summary><b>Why</b></summary>

macOS Tahoe (26.x) baselines at ~4-5 GB RAM and a steady CPU drip from ~50 Apple daemons you mostly don't use — Siri, Apple Intelligence, telemetry, ads, predictions, AirPlay, Photos analysis, etc. On a 16 GB Mac that's a third of your memory gone before any of your own apps start.

This tool kills the ones you don't need, persistently, with a single console util and no install. ~1.5 GB RAM and a few % CPU back for whatever you're actually running — compilers, browsers, VMs, model inference, video editing, games, whatever.

The ~1.5-2 GB figure is the drop in used memory on an idle M4 MacBook Pro 16 GB (macOS 26.3.1) after disabling the full default set and rebooting, compared beforehand. Your number depends on which services you actually run — check `debloat --status` for the reclaimable RAM on your own machine before and after.

</details>

<details>
<summary><b>Comparison</b></summary>

| Tool | Console UI | Curated list | Persistent | No SIP disable | Zero install |
|------|-----------|--------------|------------|----------------|--------------|
| **mac-os-debloat** | ✓ | ✓ 269 labels | ✓ | ✓ | ✓ Python stdlib |
| [launchtui](https://github.com/macournoyer/launchtui) | ✓ | ✗ generic | ✗ bootout only | ✓ | ✗ `cargo install` |
| [Silverback-Debloater](https://github.com/Wamphyre/macOS_Silverback-Debloater) | ✗ | ✓ | ✓ | ✓ | ✗ Intel-desktop only |
| [b0gdanw Tahoe gist](https://gist.github.com/b0gdanw/0c20c2fd5d0a7e6cff01849b57108967) | ✗ | ✓ | ✓ | ✗ needs SIP off | gist copy |
| LaunchControl / Lingon | GUI | ✗ | ✓ | ✓ | ✗ commercial |

</details>

---

MIT · macOS Tahoe 26.x · Apple Silicon · Python 3.10+ (ships with Xcode CLT)

**Keywords:** macOS debloat, macOS Tahoe debloat, Apple Silicon debloat, disable Apple Intelligence, disable Siri permanently, launchctl disable, free RAM macOS, mac performance mode, macOS privacy, kill Apple telemetry, macOS service manager, launchd console util, contextstored memory leak, Tahoe RAM usage, Apple Intelligence disable launchctl.
