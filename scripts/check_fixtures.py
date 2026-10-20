"""Fail loudly if a real-file test fixture is missing or differs (fixtures/manifest.json).

The fixtures are derived from James's parts and stay out of git; tests that read them
must never run against a missing or different file. Exit 1 on any problem; never skip."""
import hashlib, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    man = json.load(open(os.path.join(ROOT, "fixtures", "manifest.json")))
    bad = []
    for f in man["fixtures"]:
        p = os.path.join(ROOT, f["path"])
        if not os.path.isfile(p):
            bad.append("MISSING  %s\n  regenerate: %s" % (f["path"], f["regenerate"]))
            continue
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if h != f["sha256"]:
            bad.append("CHANGED  %s (sha256 %s != %s)\n  regenerate: %s"
                       % (f["path"], h[:12], f["sha256"][:12], f["regenerate"]))
    for b in bad:
        print(b, file=sys.stderr)
    print("fixtures: %d ok, %d bad" % (len(man["fixtures"]) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
