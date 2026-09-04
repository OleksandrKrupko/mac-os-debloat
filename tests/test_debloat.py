"""Tests for the launchd domain logic, run against a fake `launchctl`.

Each test starts from a simulated machine: plist files in fake LaunchAgents /
LaunchDaemons trees, and a fake `launchctl` that answers `print <domain>` from a
JSON state file and records every mutation. That reproduces the macOS 26.5.2 /
SIP-enabled machine from issue #8 without touching the real one.
"""
from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
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
    for label, pid in d["services"].items():
        print(f"\t\t     {pid}      - \t{label}")
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

FAKE_MDUTIL = r'''#!/usr/bin/env python3
import json, os, sys

state_path = os.environ["DEBLOAT_FAKE_STATE"]
state = json.loads(open(state_path).read())
argv = sys.argv[1:]
with open(state["log"], "a") as log:
    log.write("mdutil " + " ".join(argv) + "\n")

if argv[0] == "-s":
    print(f"{argv[1]}:\n\t{state['spotlight'][argv[1]]}")
    sys.exit(0)
if argv == ["-a", "-d"]:
    state["spotlight"] = {"/": "Indexing and searching disabled.",
                          "/System/Volumes/Data": "Error: unknown indexing state."}
elif argv == ["-a", "-i", "on"]:
    state["spotlight"] = {"/": "Indexing enabled.",
                          "/System/Volumes/Data": "Indexing enabled."}
open(state_path, "w").write(json.dumps(state))
sys.exit(0)
'''

FAKE_SUDO = '#!/bin/sh\n[ "$1" = "-v" ] && exit 0\nexec "$@"\n'


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
            "spotlight": {"/": "Indexing enabled.",
                          "/System/Volumes/Data": "Indexing enabled."},
            "domains": {
                "system": {"services": {}, "disabled": []},
                self.gui: {"services": {}, "disabled": []},
            },
        }
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in (("launchctl", FAKE_LAUNCHCTL), ("sudo", FAKE_SUDO),
                           ("mdutil", FAKE_MDUTIL)):
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
            registered=(), disabled=(), pid=0):
        if agent_plist:
            (self.agents / f"{label}.plist").touch()
        if daemon_plist:
            (self.daemons / f"{label}.plist").touch()
        for domain in registered:
            self.state["domains"][domain]["services"][label] = pid
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
                if not l.startswith(("print ", "print-disabled ", "mdutil -s "))]

    def reread(self):
        self.state = json.loads(self.state_path.read_text())


class FakeMachineTest(unittest.TestCase):
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

    def capture(self, fn, *args) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(*args)
        return out.getvalue()


class DomainTest(FakeMachineTest):
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


class RunningPidsTest(FakeMachineTest):
    def test_labels_sharing_a_last_segment_are_not_confused(self):
        """`com.apple.spindump` and `com.apple.metadata.mds.spindump` both end in
        `spindump`. Keying on that segment reported the idle one as running."""
        self.machine.add("com.example.spindump", daemon_plist=True,
                         registered=["system"], pid=0)
        self.machine.add("com.example.metadata.spindump", daemon_plist=True,
                         registered=["system"], pid=900)
        pids = self.debloat.running_pids(
            ["com.example.spindump", "com.example.metadata.spindump"])
        self.assertEqual(pids, {"com.example.metadata.spindump": [900]})

    def test_a_label_running_in_both_domains_reports_both_pids(self):
        self.machine.add("com.example.both", agent_plist=True, daemon_plist=True,
                         registered=["system"], pid=11)
        self.machine.state["domains"][self.gui]["services"]["com.example.both"] = 22
        self.machine.flush()
        self.assertEqual(self.debloat.running_pids(["com.example.both"]),
                         {"com.example.both": [11, 22]})


class StatusTest(FakeMachineTest):
    def test_status_counts_a_label_that_is_disabled_and_still_running(self):
        """macOS 26.5.2 starts jobs whose override is in place and in the right
        domain, so `disabled` alone reads as success while the daemon runs."""
        self.machine.add("com.example.ignored", daemon_plist=True,
                         registered=["system"], disabled=["system"], pid=770)
        self.machine.add("com.example.obeyed", daemon_plist=True,
                         registered=["system"], disabled=["system"], pid=0)
        secs, _ = self.sections("com.example.ignored", "com.example.obeyed")
        out = json.loads(self.capture(self.debloat.cmd_status, secs, True))
        self.assertEqual(out["disabled"], 2)
        self.assertEqual(out["disabled_but_running"], ["com.example.ignored"])


class CommandLineTest(FakeMachineTest):
    """The flags end to end, through `main()`, against the fake machine."""

    def setUp(self):
        super().setUp()
        self.debloat.BACKUP_DIR = self.machine.tmp / "backup"
        self.debloat.PRESETS_DIR = self.debloat.BACKUP_DIR / "presets"
        self.debloat.USER_LABELS_FILE = self.debloat.BACKUP_DIR / "labels.txt"
        self.debloat.PRESETS_DIR.mkdir(parents=True)
        self.debloat.mem_free_mb = lambda: 4096

    def run_cli(self, *argv) -> tuple[int, str]:
        original = sys.argv
        sys.argv = ["debloat", *argv]
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = self.debloat.main()
            return code, out.getvalue()
        finally:
            sys.argv = original

    def two_labels(self):
        self.debloat.EMBEDDED_LABELS = (
            "# === Telemetry [telemetry] ===\n"
            "com.example.telemetry  # analytics\n"
            "# === Photos ===\n"
            "com.example.photos     # photo analysis\n"
        )
        self.machine.add("com.example.telemetry", daemon_plist=True, registered=["system"])
        self.machine.add("com.example.photos", daemon_plist=True, registered=["system"])

    def test_dry_run_changes_nothing_on_the_system(self):
        self.two_labels()
        code, out = self.run_cli("--disable-all", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("[dry-run] would disable 2", out)
        self.assertEqual(self.machine.commands(), [])

    def test_preset_does_not_re_enable_a_label_outside_it(self):
        """`--preset` disables its own labels and leaves the rest as they are;
        re-enabling something the user had already turned off is data loss."""
        self.two_labels()
        self.machine.state["domains"]["system"]["disabled"].append("com.example.photos")
        self.machine.flush()
        code, _ = self.run_cli("--preset", "telemetry")
        self.assertEqual(code, 0)
        self.assertEqual(self.machine.commands(),
                         ["disable system/com.example.telemetry",
                          "bootout system/com.example.telemetry"])

    def test_restore_puts_back_exactly_the_pre_apply_state(self):
        self.two_labels()
        self.machine.state["domains"]["system"]["disabled"].append("com.example.photos")
        self.machine.flush()
        self.run_cli("--disable-all")
        self.machine.reread()
        self.assertEqual(sorted(self.machine.state["domains"]["system"]["disabled"]),
                         ["com.example.photos", "com.example.telemetry"])
        self.run_cli("--restore")
        self.machine.reread()
        self.assertEqual(self.machine.state["domains"]["system"]["disabled"],
                         ["com.example.photos"])

    def test_list_output_is_valid_input_for_preset(self):
        """The README promises the round-trip; it breaks if either the comment
        column or the section header stops parsing."""
        self.two_labels()
        _, listed = self.run_cli("--list")
        (self.debloat.PRESETS_DIR / "mine.txt").write_text(listed)
        code, out = self.run_cli("--preset", "mine", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("preset mine: 2 labels", out)

    def test_restore_turns_spotlight_back_on_when_the_apply_turned_it_off(self):
        self.two_labels()
        self.run_cli("--disable-all")
        self.machine.reread()
        self.machine.state["spotlight"] = {"/": "Indexing and searching disabled.",
                                           "/System/Volumes/Data": "Error: unknown indexing state."}
        self.machine.flush()
        self.run_cli("--restore")
        self.assertEqual(self.machine.commands()[-2:], ["mdutil -a -i on", "mdutil -a -E"])

    def test_user_labels_file_extends_the_catalog(self):
        self.two_labels()
        self.debloat.USER_LABELS_FILE.write_text("com.example.extra  # mine\n")
        self.machine.add("com.example.extra", daemon_plist=True, registered=["system"])
        code, out = self.run_cli("--disable-all", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("disable  com.example.extra", out)


class MenuTest(FakeMachineTest):
    """The TUI preset menu: which rows it offers, and what enter on one ticks."""

    def setUp(self):
        super().setUp()
        self.debloat.PRESETS_DIR = self.machine.tmp / "presets"
        self.machine.add("com.example.telemetry", daemon_plist=True, registered=["system"])
        self.machine.add("com.example.photos", daemon_plist=True, registered=["system"])
        self.secs, _ = self.sections(
            "# === Telemetry [telemetry] ===",
            "com.example.telemetry  # analytics",
            "# === Photos ===",
            "com.example.photos     # photo analysis",
        )

    def rows(self):
        self.debloat.refresh_state(self.secs)
        return [it.action for it in self.debloat.menu_section(self.secs).items]

    def test_disable_all_row_is_gone_once_everything_is_disabled(self):
        """A row that cannot change anything is a dead end; `all()` flipped to
        `any()` here leaves it on screen for every partly-disabled machine."""
        self.assertIn("disable-all", self.rows())
        self.machine.state["domains"]["system"]["disabled"] += [
            "com.example.telemetry", "com.example.photos"]
        self.machine.flush()
        self.assertEqual(self.rows(), ["preset:telemetry", "preset:balanced", "enable-all"])

    def test_enable_all_row_appears_as_soon_as_one_label_is_disabled(self):
        """The panic button must not need every label disabled to show up."""
        self.assertNotIn("enable-all", self.rows())
        self.machine.state["domains"]["system"]["disabled"].append("com.example.photos")
        self.machine.flush()
        self.assertIn("enable-all", self.rows())

    def test_preset_row_does_not_re_enable_a_label_outside_it(self):
        """Same data loss `--preset` is guarded against, on the menu path: the
        photos label the user had already turned off must stay off."""
        self.machine.state["domains"]["system"]["disabled"].append("com.example.photos")
        self.machine.flush()
        self.debloat.refresh_state(self.secs)
        self.debloat.select_for_action(self.secs, "preset:telemetry")
        self.debloat.apply_changes(self.secs)
        self.assertEqual(self.machine.commands(),
                         ["disable system/com.example.telemetry",
                          "bootout system/com.example.telemetry"])


class SpotlightStateTest(FakeMachineTest):
    def test_disabled_with_mdutil_d_reads_as_off_not_rebuilding(self):
        """After `mdutil -a -d` the Data volume answers "unknown indexing state",
        the same text a wiped index gives while it rebuilds; only `/` says
        disabled. Reading Data reported a switched-off Spotlight as INDEXING."""
        self.machine.state["spotlight"] = {"/": "Indexing and searching disabled.",
                                           "/System/Volumes/Data": "Error: unknown indexing state."}
        self.machine.flush()
        self.assertEqual(self.debloat.spotlight_state(), "off")

    def test_rebuilding_index_reads_as_indexing(self):
        self.machine.state["spotlight"] = {"/": "Error: unknown indexing state.",
                                           "/System/Volumes/Data": "Error: unknown indexing state."}
        self.machine.flush()
        self.assertEqual(self.debloat.spotlight_state(), "indexing")


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
        self.assertEqual(registered, {"com.apple.runningboardd": 441,
                                      "com.apple.kernelmanager_helper": 0,
                                      "com.apple.wifiFirmwareLoader": 0})
        self.assertEqual(disabled, {"com.apple.tipsd"})


if __name__ == "__main__":
    unittest.main()
