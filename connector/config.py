"""Connector configuration and state locations.

Key, config.toml, ledger, cursor and run work dirs live in ~/.stevecam
(override with env STEVECAM_HOME or --home, e.g. for tests). Never in the
repo. Tokens/keys are never logged.
"""
import os
import tomllib

DEFAULTS = {
    "base_url": "https://stevecad.studio/connect/v1",
    "pairing_code": "",
    "connector_name": "stevecam-rough",
    "programs_dir": "~/ai-sandbox/stevecam/out/steve",
    "engine_python": "/Applications/VibeCAD.app/Contents/Resources/bin/python",
    "repo_root": "~/ai-sandbox/stevecam",
    "poll_wait": 30,          # long-poll seconds for GET /messages
    "token_retry": 60,        # s between /token attempts while pending
    "engine_cmd": None,       # optional override for tests (list of strings)
}


def state_dir(home_override=None) -> str:
    return os.path.abspath(os.path.expanduser(
        home_override or os.environ.get("STEVECAM_HOME") or "~/.stevecam"))


def load(home_override=None) -> dict:
    cfg = dict(DEFAULTS)
    home = state_dir(home_override)
    path = os.path.join(home, "config.toml")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            user = tomllib.load(fh)
        for k in DEFAULTS:
            if k in user:
                cfg[k] = user[k]
    # env overrides (tests, ad-hoc)
    env_map = {"STEVE_BASE_URL": "base_url",
               "STEVE_PAIRING_CODE": "pairing_code",
               "STEVE_PROGRAMS_DIR": "programs_dir"}
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg["home"] = home
    cfg["programs_dir"] = os.path.abspath(os.path.expanduser(cfg["programs_dir"]))
    cfg["repo_root"] = os.path.abspath(os.path.expanduser(cfg["repo_root"]))
    return cfg
