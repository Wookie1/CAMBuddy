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
