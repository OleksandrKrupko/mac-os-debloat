#!/usr/bin/env python3
"""End-to-end tests: debloat on real macOS, inside throwaway tart VMs.

The unit tests fake `launchctl`. These run Apple's own launchd with SIP on,
through real reboots and cold boots, so a report like "overrides don't survive
a reboot" is either reproduced or disproved with evidence. Every scenario runs
on a fresh copy-on-write clone of a prepared base image, and every run writes
its evidence (launchctl state, override stores, launchd's boot log) as JSON.

  python3 tests/e2e.py prepare --os 26.5          once per macOS version
  python3 tests/e2e.py run reboot --os 26.5
  python3 tests/e2e.py run all --os 26.5 --preset balanced --out /tmp/e2e
  python3 tests/e2e.py run reboot --os 26.5 --preset disable-all     every label

Needs an Apple Silicon Mac with tart (https://tart.run) on PATH. The VM's
hardware is virtual (no battery, Bluetooth, Touch ID), so a label whose job
only loads on real hardware shows up as unregistered and is not judged.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMAGES = {
    "26.5": "ghcr.io/cirruslabs/macos-tahoe-vanilla:26.5",
    "27.0": "ghcr.io/cirruslabs/macos-golden-gate-vanilla:27.0",
}
SCENARIOS = ("apply", "restore", "reboot", "poweroff", "persist", "sip-flow")
GUEST_USER = "admin"
GUEST_PASSWORD = "admin"
GUEST_DEBLOAT = "/Users/admin/debloat"
GUEST_PROBE = "/Users/admin/probe.py"

# Reads launchd's own state for the given labels — deliberately not debloat's
# code, so a bug in debloat's domain logic can't hide in its own verdict.
PROBE = r'''
import json, subprocess, sys
labels = json.loads(sys.stdin.read())
uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
domains = ["system", f"gui/{uid}"]

def run(*argv):
    return subprocess.run(argv, capture_output=True, text=True).stdout

def block(text, header):
    rows, inside = [], False
    for line in text.splitlines():
        if line.strip() == header + " = {":
            inside = True
        elif inside and line.strip() == "}":
            break
        elif inside:
            rows.append(line.strip())
    return rows

services, disabled = {}, {}
for d in domains:
    printed = run("launchctl", "print", d)
    services[d] = {}
    for row in block(printed, "services"):
        parts = row.split()
        if len(parts) >= 3 and parts[0].lstrip("-").isdigit():
            services[d][parts[-1]] = int(parts[0])
    disabled[d] = set()
    for row in block(run("launchctl", "print-disabled", d), "disabled services"):
        name, _, state = row.partition("=>")
        if state.strip() in ("disabled", "true"):
            disabled[d].add(name.strip().strip('"'))

out = {}
for label in labels:
    registered = [d for d in domains if label in services[d]]
    out[label] = {
        "registered": registered,
        "disabled_in": [d for d in domains if label in disabled[d]],
        "pid": max([services[d][label] for d in registered] or [0]),
    }
print(json.dumps({
    "uid": uid,
    "boottime": run("sysctl", "-n", "kern.boottime").strip(),
    "labels": out,
}))
'''


def log(msg: str) -> None:
    print(f"[e2e {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tart(*argv: str, check: bool = True, timeout: float | None = None) -> str:
    r = subprocess.run(["tart", *argv], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"tart {' '.join(argv)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


class VM:
    def __init__(self, name: str, workdir: Path):
        self.name = name
        self.workdir = workdir
        self.proc: subprocess.Popen | None = None
        self.ip = ""
        askpass = workdir / "askpass.sh"
        askpass.write_text(f"#!/bin/sh\necho {GUEST_PASSWORD}\n")
        askpass.chmod(0o700)
        self.env = {**os.environ, "SSH_ASKPASS": str(askpass), "SSH_ASKPASS_REQUIRE": "force",
                    "DISPLAY": ":0"}

    def start(self) -> None:
        runlog = open(self.workdir / f"{self.name}.run.log", "a")
        self.proc = subprocess.Popen(["tart", "run", "--no-graphics", self.name],
                                     stdout=runlog, stderr=runlog, start_new_session=True)
        self.ip = tart("ip", self.name, "--wait", "300")
        self.wait_ssh(timeout=300)

    def wait_ssh(self, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.sh("true", check=False, timeout=15).returncode == 0:
                return
            time.sleep(3)
        raise RuntimeError(f"ssh to {self.name} ({self.ip}) did not come up in {timeout:.0f}s")

    def sh(self, cmd: str, check: bool = True, stdin: str | None = None,
           timeout: float = 600) -> subprocess.CompletedProcess:
        argv = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=5", "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=password,keyboard-interactive",
                f"{GUEST_USER}@{self.ip}", cmd]
        try:
            r = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                               env=self.env, stdin=None if stdin is not None else subprocess.DEVNULL,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            if check:
                raise
            return subprocess.CompletedProcess(argv, 255, "", "timeout")
        if check and r.returncode != 0:
            raise RuntimeError(f"guest `{cmd}` exited {r.returncode}: {r.stderr.strip()[-2000:]}")
        return r

    def boottime(self) -> str:
        return self.sh("sysctl -n kern.boottime").stdout.strip()

    def reboot(self) -> str:
        before = self.boottime()
        self.sh("sudo shutdown -r now", check=False, timeout=20)
        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(5)
            if self.proc is not None and self.proc.poll() is not None:
                log("tart run exited on guest reboot; starting the VM again")
                self.start()
            r = self.sh("sysctl -n kern.boottime", check=False, timeout=15)
            if r.returncode == 0 and r.stdout.strip() and r.stdout.strip() != before:
                self.wait_ssh(timeout=120)
                return r.stdout.strip()
        raise RuntimeError("guest did not come back from reboot in 600s")

    def poweroff_and_boot(self) -> str:
        self.sh("sudo shutdown -h now", check=False, timeout=20)
        if self.proc is not None:
            self.proc.wait(timeout=300)
        self.start()
        return self.boottime()

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        tart("stop", self.name, "--timeout", "30", check=False, timeout=90)
        try:
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()


def base_name(os_version: str, sip: str = "on") -> str:
    return f"debloat-e2e-base-{os_version}" + ("" if sip == "on" else "-sip-off")


CSRUTIL_DISABLE = """set timeout 60
spawn sudo csrutil disable
expect "y/n]:" { send "y\\r" }
expect "user:" { send "%s\\r" }
expect "assword" { send "%s\\r" }
expect eof
""" % (GUEST_USER, GUEST_PASSWORD)


def answer_csrutil(vm: VM, command: str) -> str:
    """Run a command that ends in `csrutil`, answering its y/n, user and
    password prompts the way a person at the terminal would."""
    vm.sh("cat > /tmp/answer.exp", stdin=(
        "set timeout 120\n"
        f"spawn {command}\n"
        "expect {\n"
        '  "y/n]:" { send "y\\r"; exp_continue }\n'
        f'  "user:" {{ send "{GUEST_USER}\\r"; exp_continue }}\n'
        f'  "assword" {{ send "{GUEST_PASSWORD}\\r"; exp_continue }}\n'
        "  eof\n"
        "}\n"))
    return vm.sh("/usr/bin/expect /tmp/answer.exp", timeout=180).stdout


def prepare_sip_off(os_version: str, workdir: Path) -> int:
    """Clone the SIP-on base and turn SIP off from inside macOS, the way a user would."""
    base = base_name(os_version, "off")
    if base in local_vms():
        log(f"{base} already exists; `tart delete {base}` to rebuild it")
        return 0
    if base_name(os_version) not in local_vms():
        raise SystemExit(f"prepare the SIP-on base first: python3 tests/e2e.py prepare --os {os_version}")
    tart("clone", base_name(os_version), base)
    vm = VM(base, workdir)
    try:
        vm.start()
        vm.sh("cat > /tmp/csrutil-disable.exp", stdin=CSRUTIL_DISABLE)
        log(vm.sh("/usr/bin/expect /tmp/csrutil-disable.exp", timeout=120).stdout.strip().splitlines()[-2])
        vm.reboot()
        status = vm.sh("csrutil status").stdout.strip()
        if "disabled" not in status:
            raise RuntimeError(f"SIP still on after csrutil disable + reboot: {status}")
        log(f"guest: {status}")
        vm.sh("sudo shutdown -h now", check=False, timeout=20)
        vm.proc.wait(timeout=300)
    except BaseException:
        vm.stop()
        tart("delete", base, check=False)
        raise
    log(f"base image ready: {base}")
    return 0


def local_vms() -> set[str]:
    rows = json.loads(tart("list", "--format", "json"))
    return {r["Name"] for r in rows if r.get("Source") == "local"}


def cmd_prepare(os_version: str, workdir: Path) -> int:
    base = base_name(os_version)
    if base in local_vms():
        log(f"{base} already exists; `tart delete {base}` to rebuild it")
        return 0
    log(f"cloning {IMAGES[os_version]} (first pull downloads ~25-50 GB)")
    tart("clone", IMAGES[os_version], base)
    vm = VM(base, workdir)
    try:
        vm.start()
        if vm.sh("xcode-select -p", check=False).returncode != 0:
            log("installing Command Line Tools for python3")
            vm.sh("touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress")
            label = vm.sh("softwareupdate -l 2>&1 | sed -n 's/^\\* Label: \\(Command Line Tools.*\\)$/\\1/p'"
                          " | sort -V | tail -1").stdout.strip()
            if not label:
                raise RuntimeError("softwareupdate lists no Command Line Tools package")
            vm.sh(f"sudo softwareupdate -i '{label}' --agree-to-license", timeout=3600)
        vm.sh("python3 -c 'import sys; assert sys.version_info >= (3, 9)'")
        vm.sh("sudo softwareupdate --schedule off", check=False)
        # The image's NOPASSWD rule sits beside %admin's password rule, and `sudo -v`
        # (debloat's first step) only skips the prompt when every matching rule is NOPASSWD.
        vm.sh("echo 'Defaults verifypw=any' | sudo tee /etc/sudoers.d/zz-e2e-verifypw >/dev/null"
              " && sudo chmod 440 /etc/sudoers.d/zz-e2e-verifypw && sudo -n -v")
        log(f"guest: {vm.sh('sw_vers -productVersion').stdout.strip()}, "
            f"{vm.sh('python3 --version').stdout.strip()}, "
            f"{vm.sh('csrutil status').stdout.strip()}")
        vm.sh("sudo shutdown -h now", check=False, timeout=20)
        vm.proc.wait(timeout=300)
    except BaseException:
        vm.stop()
        tart("delete", base, check=False)
        raise
    log(f"base image ready: {base}")
    return 0


def snapshot(vm: VM, labels: list[str], step: str) -> dict:
    probe = json.loads(vm.sh(f"python3 {GUEST_PROBE}", stdin=json.dumps(labels)).stdout)
    uid = probe["uid"]
    stores = {}
    for name in ("disabled.plist", f"disabled.{uid}.plist"):
        path = f"/private/var/db/com.apple.xpc.launchd/{name}"
        r = vm.sh(f"sudo plutil -convert json -o - {path}", check=False)
        stores[name] = json.loads(r.stdout) if r.returncode == 0 else None
    status = json.loads(vm.sh(f"python3 {GUEST_DEBLOAT} --status --json").stdout)
    return {"step": step, "probe": probe, "stores": stores, "status": status}


def boot_log(vm: VM) -> list[str]:
    # Full path: zsh in the guest has a `log` builtin that shadows /usr/bin/log.
    r = vm.sh("sudo /usr/bin/log show --last boot --style compact --predicate "
              "'process == \"launchd\" AND (eventMessage CONTAINS[c] \"disabled\" "
              "OR eventMessage CONTAINS \"Setting service\" OR eventMessage CONTAINS \"rootless\" "
              "OR eventMessage CONTAINS \"protected\" OR eventMessage CONTAINS[c] \"override\")'",
              check=False, timeout=300)
    return [line for line in r.stdout.splitlines() if "launchd" in line]


def judge(snap: dict, baseline: dict, expect_disabled: bool) -> dict:
    """Per label: an override is in effect when it is set in every domain the
    job was registered in before the apply, and a disabled job must not be
    running. Domains come from the baseline because an honoured override can
    keep a job from registering at all."""
    labels = snap["probe"]["labels"]
    domains = {k: v["registered"] for k, v in baseline["probe"]["labels"].items() if v["registered"]}
    registered = {k: v for k, v in labels.items() if k in domains}
    in_effect = sorted(k for k, v in registered.items() if set(domains[k]) <= set(v["disabled_in"]))
    running = sorted(k for k, v in registered.items() if v["pid"] > 0)
    if expect_disabled:
        wrong = sorted(set(registered) - set(in_effect))
        running_anyway = sorted(set(in_effect) & set(running))
    else:
        wrong = sorted(k for k, v in registered.items() if set(domains[k]) & set(v["disabled_in"]))
        running_anyway = []
    return {
        "step": snap["step"],
        "judged": len(registered),
        "unregistered": sorted(set(labels) - set(registered)),
        "override_in_effect": len(in_effect),
        "not_in_effect" if expect_disabled else "still_disabled": wrong,
        "disabled_but_running": running_anyway,
        "ok": not wrong and not running_anyway,
    }


def label_table(report: dict) -> str:
    """One row per label, one column per step: `off` (override in effect, no pid),
    `off+running`, `on`, `on+running`; `(unloaded)` when launchd no longer lists the
    job, `not loaded` when it never loaded on this VM."""
    snaps = report["snapshots"]
    rows = ["label\tdomains\t" + "\t".join(s["step"] for s in snaps)]
    for label in report.get("targets", []):
        seen = [s["probe"]["labels"][label]["registered"] for s in snaps if label in s["probe"]["labels"]]
        domains = next((d for d in seen if d), [])
        if not domains:
            rows.append(f"{label}\t-\t" + "\t".join("not loaded" for _ in snaps))
            continue
        cells = []
        for s in snaps:
            if label not in s["probe"]["labels"]:
                cells.append("-")
                continue
            v = s["probe"]["labels"][label]
            state = "off" if set(domains) <= set(v["disabled_in"]) else "on"
            cells.append(state + ("+running" if v["pid"] > 0 else "") + ("" if v["registered"] else " (unloaded)"))
        rows.append(f"{label}\t{','.join(domains)}\t" + "\t".join(cells))
    return "\n".join(rows) + "\n"


def run_scenario(scenario: str, os_version: str, sip_wanted: str, preset: str, cycles: int,
                 settle: int, out: Path, workdir: Path, keep: bool) -> bool:
    base = base_name(os_version, sip_wanted)
    if base not in local_vms():
        raise SystemExit(f"no base image {base}; run `python3 tests/e2e.py prepare --os {os_version}"
                         f" --sip {sip_wanted}`")
    name = f"debloat-e2e-{os_version}-sip-{sip_wanted}-{scenario}-{int(time.time())}"
    tart("clone", base, name)
    vm = VM(name, workdir)
    report: dict = {"scenario": scenario, "os": os_version, "sip": sip_wanted, "preset": preset, "vm": name,
                    "snapshots": [], "checks": [], "boot_logs": []}
    try:
        log(f"{scenario}: booting {name}")
        vm.start()
        sip = vm.sh("csrutil status").stdout.strip()
        if ("enabled" if sip_wanted == "on" else "disabled") not in sip:
            raise RuntimeError(f"guest SIP does not match --sip {sip_wanted} ({sip}); results would prove nothing")
        vm.sh(f"cat > {GUEST_DEBLOAT} && chmod +x {GUEST_DEBLOAT}",
              stdin=(REPO / "debloat").read_text())
        vm.sh(f"cat > {GUEST_PROBE}", stdin=PROBE)
        report["guest"] = {
            "macos": vm.sh("sw_vers -productVersion").stdout.strip(),
            "build": vm.sh("sw_vers -buildVersion").stdout.strip(),
            "sip": sip,
            "debloat": vm.sh(f"python3 {GUEST_DEBLOAT} --version").stdout.strip(),
        }
        log(f"guest macOS {report['guest']['macos']} ({report['guest']['build']}), {sip}")

        # Some services re-disable themselves shortly after boot; let that happen first so
        # the target list doesn't depend on how fast the dry-run ran.
        time.sleep(settle)
        selection = "--disable-all" if preset == "disable-all" else f"--preset {preset}"
        dry = vm.sh(f"python3 {GUEST_DEBLOAT} --dry-run {selection}").stdout
        labels = [line.split()[1] for line in dry.splitlines() if line.startswith("  disable  ")]
        report["targets"] = labels
        baseline = snapshot(vm, labels, "before apply")
        report["snapshots"].append(baseline)

        applied = vm.sh(f"python3 {GUEST_DEBLOAT} {selection} 2>&1", check=False)
        report["apply_output"] = applied.stdout
        if "sudo required" in applied.stdout:
            raise RuntimeError(f"apply never ran:\n{applied.stdout}")
        after = snapshot(vm, labels, "after apply")
        report["snapshots"].append(after)
        report["checks"].append(judge(after, baseline, expect_disabled=True))

        if scenario == "apply":
            time.sleep(settle)
            later = snapshot(vm, labels, f"{settle}s after apply")
            report["snapshots"].append(later)
            report["checks"].append(judge(later, baseline, expect_disabled=True))
        elif scenario == "restore":
            restored = vm.sh(f"python3 {GUEST_DEBLOAT} --restore 2>&1", check=False)
            report["restore_output"] = restored.stdout
            snap = snapshot(vm, labels, "after --restore")
            report["snapshots"].append(snap)
            report["checks"].append(judge(snap, baseline, expect_disabled=False))
        elif scenario == "persist":
            installed = vm.sh("test -f /Library/LaunchDaemons/io.github.oleksandrkrupko.debloat.plist",
                              check=False).returncode == 0
            report["checks"].append({"step": "apply installed the boot daemon", "sip_now": "installed" if installed
                                     else "not installed", "ok": installed})
            for n in range(1, cycles + 1):
                log(f"persist: reboot {n}/{cycles}")
                vm.reboot()
                time.sleep(settle)
                early = snapshot(vm, labels, f"reboot {n}, {settle}s after boot")
                report["snapshots"].append(early)
                report["checks"].append(judge(early, baseline, expect_disabled=True))
                deadline = time.time() + 900
                while time.time() < deadline:
                    last = vm.sh("cat '/Library/Application Support/mac-os-debloat/last-run.json'",
                                 check=False)
                    if last.returncode == 0 and '"respawners"' in last.stdout:
                        break
                    time.sleep(15)
                else:
                    raise RuntimeError("boot daemon did not finish its passes in 15 minutes")
                done = snapshot(vm, labels, f"reboot {n}, after the daemon's last pass")
                report["snapshots"].append(done)
                report.setdefault("daemon_runs", []).append(json.loads(last.stdout))
                report["boot_logs"].append({"step": done["step"], "lines": boot_log(vm)})
                report["checks"].append(judge(done, baseline, expect_disabled=True))
                vm.sh("sudo rm -f '/Library/Application Support/mac-os-debloat/last-run.json'")
            report["enable_all_output"] = vm.sh(f"python3 {GUEST_DEBLOAT} --enable-all 2>&1").stdout
            leftovers = vm.sh("ls -d /Library/LaunchDaemons/io.github.oleksandrkrupko.debloat.plist "
                              "'/Library/Application Support/mac-os-debloat' 2>/dev/null", check=False).stdout
            report["checks"].append({"step": "--enable-all removed the boot daemon", "judged": 0, "unregistered": [],
                                     "override_in_effect": 0, "not_in_effect": [],
                                     "disabled_but_running": [], "leftovers": leftovers.split(),
                                     "ok": not leftovers.strip()})
        elif scenario == "sip-flow":
            report["disable_sip_output"] = answer_csrutil(vm, f"python3 {GUEST_DEBLOAT} --disable-sip")
            vm.reboot()
            time.sleep(settle)
            sip_now = vm.sh("csrutil status").stdout.strip()
            report["checks"].append({"step": "debloat --disable-sip + reboot", "sip_now": sip_now,
                                     "ok": "disabled" in sip_now})
            dry = vm.sh(f"python3 {GUEST_DEBLOAT} --dry-run --disable-all").stdout
            labels = sorted(set(labels) | {line.split()[1] for line in dry.splitlines()
                                           if line.startswith("  disable  ")})
            report["targets"] = labels
            sip_off_start = snapshot(vm, labels, "SIP off, before --disable-all")
            report["snapshots"].append(sip_off_start)
            # SIP-free labels were disabled before SIP went off, so with SIP off they
            # never registered; their domains come from the stock snapshot.
            baseline = json.loads(json.dumps(sip_off_start))
            for label, v in report["snapshots"][0]["probe"]["labels"].items():
                if v["registered"]:
                    baseline["probe"]["labels"][label] = v
            vm.sh(f"python3 {GUEST_DEBLOAT} --disable-all 2>&1", check=False)
            leftover = vm.sh("ls /Library/LaunchDaemons/io.github.oleksandrkrupko.debloat.plist 2>/dev/null",
                             check=False).stdout.strip()
            report["checks"].append({"step": "SIP-off apply removed the boot daemon",
                                     "sip_now": leftover or "removed", "ok": not leftover})
            for n in range(1, cycles + 1):
                vm.reboot()
                time.sleep(settle)
                snap = snapshot(vm, labels, f"SIP off, --disable-all, reboot {n}")
                report["snapshots"].append(snap)
                report["checks"].append(judge(snap, baseline, expect_disabled=True))
            vm.sh(f"python3 {GUEST_DEBLOAT} --enable-all 2>&1", check=False)
            report["enable_sip_output"] = answer_csrutil(vm, f"python3 {GUEST_DEBLOAT} --enable-sip")
            vm.reboot()
            time.sleep(settle)
            sip_now = vm.sh("csrutil status").stdout.strip()
            back = snapshot(vm, labels, "--enable-all + --enable-sip + reboot")
            report["snapshots"].append(back)
            report["checks"].append({"step": "debloat --enable-sip + reboot", "sip_now": sip_now,
                                     "ok": "enabled" in sip_now})
            report["checks"].append(judge(back, baseline, expect_disabled=False))
        elif scenario in ("reboot", "poweroff"):
            for n in range(1, cycles + 1):
                step = f"after {'reboot' if scenario == 'reboot' else 'power-off + cold boot'} {n}"
                log(f"{scenario}: cycle {n}/{cycles}")
                vm.reboot() if scenario == "reboot" else vm.poweroff_and_boot()
                time.sleep(settle)
                snap = snapshot(vm, labels, step)
                report["snapshots"].append(snap)
                report["boot_logs"].append({"step": step, "lines": boot_log(vm)})
                report["checks"].append(judge(snap, baseline, expect_disabled=True))
    finally:
        vm.stop()
        if not keep:
            tart("delete", name, check=False)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{os_version}-sip-{sip_wanted}-{scenario}.json").write_text(json.dumps(report, indent=2, default=list))
        (out / f"{os_version}-sip-{sip_wanted}-{scenario}-labels.tsv").write_text(label_table(report))

    for c in report["checks"]:
        bad = c.get("not_in_effect", c.get("still_disabled", []))
        verdict = lambda ok: "PASS" if ok else "FAIL"
        if "sip_now" in c:
            print(f"  {c['step']}\n    {verdict(c['ok'])}  {c['sip_now']}")
            continue
        if "leftovers" in c:
            print(f"  {c['step']}\n    {verdict(c['ok'])}  files removed       "
                  f"{'all' if c['ok'] else ', '.join(c['leftovers'])}")
            continue
        print(f"  {c['step']}  ({c['judged']} judged, {len(c['unregistered'])} not loaded on this VM)")
        if "not_in_effect" in c:
            print(f"    {verdict(not bad)}  override in effect  {c['override_in_effect']}/{c['judged']}")
            stopped = (f"{verdict(not c['disabled_but_running'])}  stopped             "
                       f"{c['override_in_effect'] - len(c['disabled_but_running'])}/{c['override_in_effect']}"
                       if c["override_in_effect"] else "n/a   stopped             no override in effect")
            print(f"    {stopped}")
        else:
            print(f"    {verdict(not bad)}  back to pre-apply   {c['judged'] - len(bad)}/{c['judged']}")
        for kind, found in (("not in effect" if "not_in_effect" in c else "still disabled", bad),
                            ("running anyway", c["disabled_but_running"])):
            for label in found[:20]:
                print(f"          {kind}: {label}")
            if len(found) > 20:
                print(f"          ... {len(found) - 20} more {kind} (see {os_version}-sip-{sip_wanted}-{scenario}-labels.tsv)")
    return all(c["ok"] for c in report["checks"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build the base image for one macOS version")
    p.add_argument("--os", choices=sorted(IMAGES), required=True)
    p.add_argument("--sip", choices=("on", "off"), default="on",
                   help="off: clone the SIP-on base and run `csrutil disable` inside it")
    r = sub.add_parser("run", help="run one scenario, or all of them, on fresh clones")
    r.add_argument("scenario", choices=(*SCENARIOS, "all"))
    r.add_argument("--os", choices=sorted(IMAGES), required=True)
    r.add_argument("--sip", choices=("on", "off"), default="on")
    r.add_argument("--preset", default="telemetry",
                   help="telemetry, balanced, a custom preset name, or disable-all for every label")
    r.add_argument("--cycles", type=int, default=2, help="reboots / cold boots per scenario")
    r.add_argument("--settle", type=int, default=60, help="seconds to wait after an apply or a boot before judging again")
    r.add_argument("--out", type=Path, help="evidence dir (default: a new temp dir)")
    r.add_argument("--keep", action="store_true", help="keep the VM clone for inspection")
    args = ap.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="debloat-e2e-"))
    if args.cmd == "prepare":
        return cmd_prepare(args.os, workdir) if args.sip == "on" else prepare_sip_off(args.os, workdir)
    out = args.out or workdir
    ok = True
    for scenario in SCENARIOS if args.scenario == "all" else (args.scenario,):
        ok = run_scenario(scenario, args.os, args.sip, args.preset, args.cycles, args.settle, out,
                          workdir, args.keep) and ok
    log(f"evidence: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
