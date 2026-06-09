# mac-os-debloat

**Debloat your Mac from the terminal. Zero dependencies. Zero install.**

Interactive console util to disable 76 non-essential macOS launchd services. Reclaims ~1.5 GB RAM and a chunk of CPU for whatever heavy work you're actually doing. Persistent across reboot. Fully reversible. Built for macOS Tahoe 26.x on Apple Silicon.

```bash
curl -fsSL https://raw.githubusercontent.com/OleksandrKrupko/mac-os-debloat/main/debloat -o debloat && chmod +x debloat && ./debloat
```

Or via Homebrew:

```bash
brew install OleksandrKrupko/debloat/debloat
```

## Screenshot

```
mac-os-debloat  —  space=toggle  a=all  n=none  enter=apply  r=reload  q=quit
pending changes: 4   (checked = enabled/running, unchecked = disabled)

── Siri / voice assistant ──────────────────────────────────────────────────
 *[ ]  com.apple.assistantd                          Siri core
 *[ ]  com.apple.Siri.agent                          Siri agent
  [ ]  com.apple.SiriTTSService.TrainingAgent        Siri voice training
  [ ]  com.apple.siriinferenced                      on-device Siri inference
 *[ ]  com.apple.siriknowledged                      Siri knowledge graph
  [ ]  com.apple.assistant_cdmd                      Siri continuous dialog manager
  [✓]  com.apple.parsecd                             Siri/Spotlight suggestions backend
  [✓]  com.apple.parsec-fbf                          Siri Suggestions feedback
 *[ ]  com.apple.intelligencecontextd                Apple Intelligence context runtime
  [✓]  com.apple.intelligenceplatformd               Apple Intelligence platform

── Apple Intelligence (Tahoe) ────────────────────────────────────────────── ↓
  [✓]  com.apple.intelligenced                       Apple Intelligence core
► [✓]  com.apple.aiml.appleintelligenceserviced      AI/ML service
  [✓]  com.apple.PrivacyIntelligence                 privacy-preserving AI
  [✓]  com.apple.mlruntime                           ML runtime
  [✓]  com.apple.generativeexperiencesd              Writing Tools / generative AI
  [✓]  com.apple.contextstored                       context store (>30GB memory leak)
```

<details>
<summary><b>What it disables</b></summary>

76 labels across 21 sections:

- Siri / voice assistant (11)
- Apple Intelligence — Tahoe (10), incl. `contextstored` (known >30 GB memory leak)
- Telemetry / analytics (2)
- AirDrop / Continuity (2)
- Diagnostics / crash reports (4)
- Apple ads (3)
- Proactive / predictive (4)
- Game Center / AirPlay receiver (4)
- Photos analysis (2)
- News / Stocks / Weather (3)
- Apple ID nags / Family (2)
- iMessage / FaceTime / phone relay (5)
- HomeKit (1)
- Apple Mail / Calendar / Contacts / Reminders (4)
- Speech / dictation (2)
- Wallpaper / thumbnails (2)
- App Store + update nags (3, keeps `softwareupdated` for security)
- Misc dead weight (5)
- iCloud (2)
- Location / prediction extras (3)
- Misc (2)

Full curated list with per-label comments lives inside the script (`EMBEDDED_LABELS`).

</details>

<details>
<summary><b>Keys</b></summary>

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | navigate |
| `PgUp` / `PgDn` | jump 10 |
| `space` | toggle current |
| `a` | check all |
| `n` | uncheck all |
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

Tested on M4 MacBook Pro 16 GB · macOS 26.3.1.

</details>

<details>
<summary><b>Comparison</b></summary>

| Tool | Console UI | Curated list | Persistent | Zero install |
|------|-----------|--------------|------------|--------------|
| **mac-os-debloat** | ✓ | ✓ 76 labels | ✓ | ✓ Python stdlib |
| [launchtui](https://github.com/macournoyer/launchtui) | ✓ | ✗ generic | ✗ bootout only | ✗ `cargo install` |
| [Silverback-Debloater](https://github.com/Wamphyre/macOS_Silverback-Debloater) | ✗ | ✓ | ✓ | ✗ Intel-desktop only |
| [b0gdanw Tahoe gist](https://gist.github.com/b0gdanw/0c20c2fd5d0a7e6cff01849b57108967) | ✗ | ✓ | ✓ | gist copy |
| LaunchControl / Lingon | GUI | ✗ | ✓ | ✗ commercial |

</details>

---

MIT · macOS Tahoe 26.x · Apple Silicon · Python 3.10+ (ships with Xcode CLT)

**Keywords:** macOS debloat, macOS Tahoe debloat, Apple Silicon debloat, disable Apple Intelligence, disable Siri permanently, launchctl disable, free RAM macOS, mac performance mode, macOS privacy, kill Apple telemetry, macOS service manager, launchd console util, contextstored memory leak, Tahoe RAM usage, Apple Intelligence disable launchctl.
