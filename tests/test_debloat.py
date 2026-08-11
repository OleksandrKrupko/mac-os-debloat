"""Tests for the launchd domain logic, run against a fake `launchctl`.

Each test starts from a simulated machine: plist files in fake LaunchAgents /
LaunchDaemons trees, and a fake `launchctl` that answers `print <domain>` from a
JSON state file and records every mutation. That reproduces the macOS 26.5.2 /
SIP-enabled machine from issue #8 without touching the real one.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAKE_LAUNCHCTL = r'''#!/usr/bin/env python3
import json, os, sys

state_path = os.environ["DEBLOAT_FAKE_STATE"]
state = json.loads(open(state_path).read())
argv = sys.argv[1:]
with open(state["log"], "a") as log:
    log.write(" ".join(argv) + "\n")

action = argv[0]
if action == "print-disabled":
    print(f"{argv[1]}/ = {{")
    for label in state["domains"][argv[1]]["disabled"]:
        print(f'\t"{label}" => true')
    print("}")
    sys.exit(0)

if action == "print":
    domain = argv[1]
    d = state["domains"].get(domain)
    if d is None:
        sys.stderr.write(f"Could not find domain {domain}\n")
        sys.exit(113)
    print(f"{domain} = {{")
    print("\tactive count = 42")
    print("\tattractive services = {")
    print("\t\tcom.apple.SomeBlastDoorService")
    print("\t}")
    print("\tservices = {")
    for label in d["services"]:
        print(f"\t\t     0      - \t{label}")
    print("\t}")
    print("\tdisabled services = {")
    for label in d["disabled"]:
        print(f'\t\t"{label}" => disabled')
    for label in d.get("explicitly_enabled", []):
        print(f'\t\t"{label}" => enabled')
    print("\t}")
    print("}")
    sys.exit(0)

fail = state.get("fail", {}).get(action)
if fail:
    sys.stderr.write(fail["message"] + "\n")
    sys.exit(fail["code"])

label = argv[1].rsplit("/", 1)[1]
domain = argv[1][: -(len(label) + 1)]
target = state["domains"][domain]["disabled"]
if action == "disable" and state.get("overrides_land", True):
    if label not in target:
        target.append(label)
elif action == "enable":
    if label in target:
        target.remove(label)
open(state_path, "w").write(json.dumps(state))
sys.exit(0)
'''

FAKE_SUDO = '#!/bin/sh\nexec "$@"\n'


def load_debloat():
    loader = importlib.machinery.SourceFileLoader("debloat", str(REPO / "debloat"))
    spec = importlib.util.spec_from_loader("debloat", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["debloat"] = module
    spec.loader.exec_module(module)
    return module


class FakeMachine:
    """A simulated macOS launchd setup: plist trees + a fake launchctl on PATH."""

    def __init__(self, tmp: Path, debloat):
        self.tmp = tmp
        self.debloat = debloat
        self.gui = f"gui/{debloat.UID}"
        self.agents = tmp / "LaunchAgents"
        self.daemons = tmp / "LaunchDaemons"
        self.agents.mkdir()
        self.daemons.mkdir()
        self.log = tmp / "launchctl.log"
        self.log.touch()
        self.state_path = tmp / "state.json"
        self.state = {
            "log": str(self.log),
            "overrides_land": True,
            "fail": {},
            "domains": {
                "system": {"services": [], "disabled": []},
                self.gui: {"services": [], "disabled": []},
            },
        }
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in (("launchctl", FAKE_LAUNCHCTL), ("sudo", FAKE_SUDO)):
            path = bindir / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = f"{bindir}:{os.environ['PATH']}"
        os.environ["DEBLOAT_FAKE_STATE"] = str(self.state_path)
        debloat.LAUNCHD_DIRS = (str(self.daemons), str(self.agents))
        self.flush()

    def flush(self):
        self.state_path.write_text(json.dumps(self.state))

    def add(self, label: str, *, agent_plist=False, daemon_plist=False,
            registered=(), disabled=()):
        if agent_plist:
            (self.agents / f"{label}.plist").touch()
        if daemon_plist:
            (self.daemons / f"{label}.plist").touch()
        for domain in registered:
            self.state["domains"][domain]["services"].append(label)
        for domain in disabled:
            self.state["domains"][domain]["disabled"].append(label)
        self.flush()

    def fail(self, action: str, code: int, message: str):
        self.state["fail"][action] = {"code": code, "message": message}
        self.flush()

    def swallow_overrides(self):
        self.state["overrides_land"] = False
        self.flush()

    def commands(self) -> list[str]:
        return [l for l in self.log.read_text().splitlines()
                if not l.startswith(("print ", "print-disabled "))]

    def reread(self):
        self.state = json.loads(self.state_path.read_text())


class DomainTest(unittest.TestCase):
    def setUp(self):
        self.debloat = load_debloat()
        self._path = os.environ["PATH"]
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.addCleanup(lambda: os.environ.update(PATH=self._path))
        self.machine = FakeMachine(Path(tmpdir.name), self.debloat)
        self.gui = self.machine.gui

    def sections(self, *labels):
        secs = self.debloat.parse_labels("\n".join(labels))
        absent = self.debloat.drop_absent_labels(secs)
        return secs, absent

    def items(self, secs):
        return {it.label: it for sec in secs for it in sec.items}

    # --- issue #8 part 2: --status unions the domains ---

    def test_override_in_a_domain_the_job_does_not_live_in_is_not_disabled(self):
        """The 199-label case measured on the reporter's machine: the agent runs
        in gui/$UID, the override sits in `system`, so it never takes effect."""
        self.machine.add("com.example.agent", agent_plist=True,
                         registered=[self.gui], disabled=["system"])
        secs, _ = self.sections("com.example.agent")
        self.debloat.refresh_state(secs)
        item = self.items(secs)["com.example.agent"]
        self.assertFalse(item.disabled)
        self.assertEqual(item.domains, {self.gui})

    def test_job_in_both_domains_needs_an_override_in_both(self):
        """com.apple.cloudd / rapportd are registered in system and gui/$UID;
        one override leaves the other copy running."""
        self.machine.add("com.example.both", agent_plist=True, daemon_plist=True,
                         registered=["system", self.gui], disabled=[self.gui])
        secs, _ = self.sections("com.example.both")
        self.debloat.refresh_state(secs)
        item = self.items(secs)["com.example.both"]
        self.assertFalse(item.disabled)
        self.assertEqual(item.domains, {"system", self.gui})

        self.machine.state["domains"]["system"]["disabled"].append("com.example.both")
        self.machine.flush()
        self.debloat.refresh_state(secs)
        self.assertTrue(item.disabled)

    def test_label_registered_without_a_plist_file_is_kept(self):
        """12 catalog labels (CommCenter, studentd, ...) have no plist in the
        standard dirs; they must not be pruned as phantoms."""
        self.machine.add("com.example.plistless", registered=["system"])
        secs, absent = self.sections("com.example.plistless")
        self.assertEqual(absent, [])
        self.assertEqual(self.items(secs)["com.example.plistless"].domains, {"system"})

    def test_label_nowhere_on_the_system_is_dropped(self):
        secs, absent = self.sections("com.example.ghost")
        self.assertEqual(absent, ["com.example.ghost"])
        self.assertEqual(secs, [])

    # --- issue #8 part 1: overrides written to the wrong domain ---

    def test_apply_only_touches_domains_the_job_is_registered_in(self):
        self.machine.add("com.example.agent", agent_plist=True, registered=[self.gui])
        secs, _ = self.sections("com.example.agent")
        self.debloat.refresh_state(secs)
        self.items(secs)["com.example.agent"].selected = False
        self.debloat.apply_changes(secs)
        self.assertEqual(self.machine.commands(),
                         [f"disable {self.gui}/com.example.agent",
                          f"bootout {self.gui}/com.example.agent"])

    def test_apply_reports_overrides_that_did_not_take_effect(self):
        """launchctl exits 0 but the override is not in effect afterwards — the
        silent failure that let --status report success while services ran."""
        self.machine.add("com.example.agent", agent_plist=True, registered=[self.gui])
        secs, _ = self.sections("com.example.agent")
        self.machine.swallow_overrides()
        self.debloat.refresh_state(secs)
        self.items(secs)["com.example.agent"].selected = False
        result = self.debloat.apply_changes(secs)
        self.assertEqual(result["not_disabled"], ["com.example.agent"])

    # --- issue #8 part 3: bootout / disable failures swallowed ---

    def test_sip_bootout_failure_is_reported(self):
        self.machine.add("com.example.agent", agent_plist=True, registered=[self.gui])
        self.machine.fail("bootout", 150, "Boot-out failed: 150: Operation not "
                          "permitted while System Integrity Protection is engaged")
        secs, _ = self.sections("com.example.agent")
        self.debloat.refresh_state(secs)
        self.items(secs)["com.example.agent"].selected = False
        result = self.debloat.apply_changes(secs)
        self.assertEqual(list(result["bootout_failures"].values()), [1])
        self.assertIn("System Integrity Protection",
                      next(iter(result["bootout_failures"])))
        self.assertEqual(result["not_disabled"], [])

    def test_disable_failure_is_reported_per_label(self):
        self.machine.add("com.example.agent", agent_plist=True, registered=[self.gui])
        self.machine.fail("disable", 1, "Could not modify service: 150: Operation "
                          "not permitted")
        secs, _ = self.sections("com.example.agent")
        self.debloat.refresh_state(secs)
        self.items(secs)["com.example.agent"].selected = False
        result = self.debloat.apply_changes(secs)
        self.assertEqual(result["override_failures"],
                         [(f"disable {self.gui}/com.example.agent",
                           "Could not modify service: 150: Operation not permitted")])
        self.assertEqual(result["not_disabled"], ["com.example.agent"])


class DomainStateParseTest(unittest.TestCase):
    """`launchctl print <domain>` output, verbatim shape, with the neighbouring
    blocks that must not leak into either set."""

    OUTPUT = """\
system = {
\tactive count = 588
\tattractive services = {
\t\tcom.apple.MessagesBlastDoorService
\t}
\tservices = {
\t\t     441      - \tcom.apple.runningboardd
\t\t       0   (pe) \tcom.apple.kernelmanager_helper
\t\t       0      1 \tcom.apple.wifiFirmwareLoader
\t}
\tendpoints = {
\t\t\tcom.apple.not.a.service
\t}
\tdisabled services = {
\t\t"com.apple.tipsd" => disabled
\t\t"org.openvpn.helper" => enabled
\t}
}
"""

    def test_services_and_disabled_blocks_are_read_separately(self):
        debloat = load_debloat()
        original = subprocess.run
        def fake_run(cmd, **kwargs):
            assert cmd[:2] == ["launchctl", "print"], cmd
            return subprocess.CompletedProcess(cmd, 0, self.OUTPUT, "")
        subprocess.run = fake_run
        try:
            registered, disabled = debloat.domain_state("system")
        finally:
            subprocess.run = original
        self.assertEqual(registered, {"com.apple.runningboardd",
                                      "com.apple.kernelmanager_helper",
                                      "com.apple.wifiFirmwareLoader"})
        self.assertEqual(disabled, {"com.apple.tipsd"})


if __name__ == "__main__":
    unittest.main()
