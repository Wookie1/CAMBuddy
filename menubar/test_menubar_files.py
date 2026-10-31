"""Task MENUBAR red test (d): the menubar/ deliverables are well-formed.

Rendered LaunchAgent plist lints with plutil and carries the required keys;
no ckern/jobs env overrides in the menubar sources; SteveCAM.swift passes
`swiftc -typecheck -parse-as-library` and never kills by name; the shell
scripts pass `bash -n`.

Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        menubar/test_menubar_files.py

Note: the forbidden env names are built from fragments and the scan covers
only the deliverable sources (*.swift, *.sh, *.plist.in, README.md), so
this file and the task brief cannot match themselves.
"""
import os
import plistlib
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LANE_TEST = os.path.abspath(__file__)

FORBIDDEN = ["ZMAP_NO_" "CKERN", "STEVECAM_NO_" "CKERN", "ZMAP_" "JOBS"]


def _menubar_files():
    out = []
    for root, _dirs, names in os.walk(HERE):
        if ".git" in root:
            continue
        for n in sorted(names):
            if n == os.path.basename(LANE_TEST) or n == "TASK_MENUBAR.md":
                continue
            if n.endswith((".swift", ".sh", ".plist.in")) or n == "README.md":
                out.append(os.path.join(root, n))
    return out


def test_plist_template_renders_and_lints(tmp_path):
    src = os.path.join(HERE, "com.stevecam.connector.plist.in")
    text = open(src).read()
    rendered = text.replace("@REPO@", REPO).replace(
        "@HOME@", str(tmp_path))
    path = tmp_path / "com.stevecam.connector.plist"
    with open(path, "w") as fh:
        fh.write(rendered)
    out = subprocess.run(["plutil", "-lint", str(path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    d = plistlib.loads(path.read_bytes())
    assert d["Label"] == "com.stevecam.connector"
    assert d["ProgramArguments"] == ["/opt/homebrew/bin/python3",
                                     os.path.join(REPO, "connector",
                                                  "connector.py")]
    assert d["WorkingDirectory"] == REPO
    assert d["RunAtLoad"] is True
    assert d["KeepAlive"] == {"SuccessfulExit": False}
    assert d["ThrottleInterval"] == 10
    home = str(tmp_path)
    assert d["StandardOutPath"] == os.path.join(home, ".stevecam",
                                                "connector.log")
    assert d["StandardErrorPath"] == os.path.join(home, ".stevecam",
                                                  "connector.log")
    env = d["EnvironmentVariables"]
    assert "/usr/bin" in env["PATH"]
    assert "/opt/homebrew/bin" in env["PATH"]
    assert env["HOME"] == home


def test_no_ckern_env_names_in_menubar():
    hits = []
    for path in _menubar_files():
        text = open(path, errors="replace").read()
        for bad in FORBIDDEN:
            if bad in text:
                hits.append("%s: %s" % (os.path.basename(path), bad))
    assert not hits, hits


def test_swift_typechecks():
    src = os.path.join(HERE, "SteveCAM.swift")
    out = subprocess.run(["/usr/bin/swiftc", "-typecheck",
                          "-parse-as-library", src],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]


def test_swift_never_kills_by_name():
    text = open(os.path.join(HERE, "SteveCAM.swift")).read()
    for bad in ("pkill", "killall", "kill -9"):
        assert bad not in text


def test_shell_scripts_parse():
    scripts = [p for p in _menubar_files() if p.endswith(".sh")]
    assert scripts
    for path in scripts:
        out = subprocess.run(["bash", "-n", path], capture_output=True,
                             text=True)
        assert out.returncode == 0, "%s: %s" % (path, out.stderr)


# ------------------------------------------------ MENUBAR2: busy guard ----

def test_swift_stop_guard():
    """MENUBAR2: the Stop/Restart busy guard in SteveCAM.swift. Checks:
    1. the exact alert text and the Stop / Cancel buttons;
    2. the pure decision function stopDecision(state:force:fromURL:) with
       proceed/confirm/refuse, force read only from the URL (force=1) and
       stevecam://start unchanged;
    3. a refusal is recorded ("... refused <action>: run in progress");
    4. every kill( call site is reached only after the decision: scanning
       the file brace-by-brace, the function whose body contains a kill(
       (code after "//" comments ignored) must be either pidAlive
       (kill(pid, 0) liveness probe, sends no signal) or performStop, the
       single SIGTERM executor, which takes an explicit `confirmed: Bool`
       and returns unless it is true; stop() and restart() call
       stopDecision( before performStop(, and kill(pid, SIGTERM) appears
       exactly once in the file.
    """
    text = open(os.path.join(HERE, "SteveCAM.swift")).read()
    # 1. the alert shown by the menu's Stop/Restart while a run is in progress
    assert '"A run is in progress. Stop anyway?"' in text
    assert 'addButton(withTitle: "Stop")' in text
    assert 'addButton(withTitle: "Cancel")' in text
    # 2. pure decision + force=1 for URLs + start untouched
    assert "func stopDecision(state: String?, force: Bool, fromURL: Bool)" \
        in text
    assert "-> StopDecision" in text
    for case in ("case proceed", "case confirm", "case refuse"):
        assert case in text, case
    assert "force=1" in text                       # stevecam://stop?force=1
    assert 'stop(fromURL: true, force: force)' in text
    assert 'restart(fromURL: true, force: force)' in text
    assert 'case "start": start()' in text
    # 3. refusals are logged to ~/.stevecam/menubar.log
    assert 'logRefusal("stop")' in text
    assert 'logRefusal("restart")' in text
    assert "run in progress" in text               # the logged line
    # 4. kill( sites are gated by the decision (see docstring)
    #    brace-aware scan: a kill( belongs to the func whose { opened first
    #    at or below the current depth; text after "//" does not count
    lines = [re.sub(r"//.*", "", ln) for ln in text.splitlines()]
    depth = 0
    stack = []            # [(func_name, depth_at_open)]
    bodies = {}           # func name -> its code lines
    killers = set()
    for ln in lines:
        m = re.search(r"\bfunc (\w+)", ln)
        opens, closes = ln.count("{"), ln.count("}")
        pre = depth
        depth += opens - closes
        if m:
            stack.append((m.group(1), pre + (1 if opens else 0)))
            bodies.setdefault(m.group(1), [])
        for fn, d in stack:
            if pre >= d:
                bodies[fn].append(ln)
        if "kill(" in ln:
            owner = [fn for fn, d in stack if pre >= d]
            assert owner, "kill( outside any func"
            killers.add(owner[-1])
        while stack and depth < stack[-1][1]:
            stack.pop()
    assert killers <= {"pidAlive", "performStop"}, sorted(killers)
    for name in killers:
        body = "\n".join(bodies[name])
        if name == "pidAlive":
            assert "kill(pid, 0)" in body          # probe, not a signal
        else:
            assert "confirmed: Bool" in body       # performStop's parameter
            assert "guard confirmed else" in body
    assert text.count("kill(pid, SIGTERM)") == 1   # the single executor
    for name in ("stop", "restart"):
        body = "\n".join(bodies[name])
        assert "stopDecision(" in body and "performStop(" in body
        assert body.index("stopDecision(") < body.index("performStop(")


# ------------------------------------------- MENUBAR3: Settings via link --

def test_settings_uses_settingslink():
    """MENUBAR3: the menu opens the SwiftUI Settings scene through
    SettingsLink (the legacy showSettingsWindow:/showPreferencesWindow:
    selectors are broken on this macOS). Checks:
    1. SteveCAM.swift contains "SettingsLink" inside an
       `#available(macOS 14` branch, i.e. on a line after
       `if #available(macOS 14` and before the closing `} else {` that
       carries the macOS 13 Button fallback;
    2. `swiftc -typecheck -parse-as-library` is green.
    """
    text = open(os.path.join(HERE, "SteveCAM.swift")).read()
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.search(r"if\s+#available\(\s*macOS\s+14\b", ln):
            start = i
            break
    assert start is not None, "no `if #available(macOS 14 ...` branch"
    end = None
    for j in range(start, len(lines)):
        if re.search(r"\}\s*else\b", lines[j]):
            end = j
            break
    assert end is not None, "#available(macOS 14 branch has no `} else {`"
    branch = "\n".join(lines[start:end])
    assert "SettingsLink" in branch, \
        "SettingsLink not inside the #available(macOS 14 branch"
    assert 'Text("Settings...")' in branch
    assert 'Button("Settings...") { openSettingsWindow() }' \
        in "\n".join(lines[end:end + 4]), "macOS 13 fallback missing"
    src = os.path.join(HERE, "SteveCAM.swift")
    out = subprocess.run(["/usr/bin/swiftc", "-typecheck",
                          "-parse-as-library", src],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]


# --------------------------------------------- PANELCANCEL5: ExitTimeOut --

def test_plist_exit_timeout(tmp_path):
    """PANELCANCEL5: the rendered plist gives the connector a bounded,
    generous shutdown window: ExitTimeOut is an int >= 30 (launchd sends
    SIGTERM at logout/stop and SIGKILLs after ExitTimeOut; the connector's
    worst-case tail is ~23 s, see connector.py's SHUTDOWN_* constants)."""
    src = os.path.join(HERE, "com.stevecam.connector.plist.in")
    text = open(src).read()
    rendered = text.replace("@REPO@", REPO).replace("@HOME@", str(tmp_path))
    path = tmp_path / "com.stevecam.connector.plist"
    with open(path, "w") as fh:
        fh.write(rendered)
    d = plistlib.loads(path.read_bytes())
    timeout = d.get("ExitTimeOut")
    assert isinstance(timeout, int) and not isinstance(timeout, bool), \
        "ExitTimeOut missing or not an int: %r" % (timeout,)
    assert timeout >= 30, "ExitTimeOut %r < 30" % timeout
