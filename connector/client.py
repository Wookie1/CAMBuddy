"""Signed HTTPS client for the STEVE connect API (stdlib urllib only).

Handles enrollment, bearer token (refreshed before expiry), signed requests,
long-poll messages, run reports, file uploads, events, panels, and plain
downloads of STEVE input files with their one-time ticket headers.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import crypto


class SteveError(Exception):
    def __init__(self, code, message, http=0):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.http = http


class SteveClient:
    def __init__(self, base_url: str, sk):
        self.base = base_url.rstrip("/")
        p = urllib.parse.urlparse(self.base)
        self.base_path = p.path  # e.g. /connect/v1
        self.sk = sk
        self.token = None
        self.token_exp = 0.0
        self.timeout = 60.0

    # ---------------------------------------------------------- plumbing --
    def _request(self, method, ep, query="", body=b"", media=None,
                 auth=True, extra_headers=None):
        if auth:  # never from get_token itself: that recursed forever
            self._maybe_refresh()
        headers = crypto.sign_request(self.sk, method, self.base_path + ep,
                                     query, body)
        headers["Accept"] = "application/json"
        if media:
            headers["Content-Type"] = media
        if auth and self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        if extra_headers:
            headers.update(extra_headers)
        url = self.base + ep + (("?" + query) if query else "")
        req = urllib.request.Request(url, data=body or None, method=method,
                                    headers=headers)
        return self._send(req)

    def _send(self, req):
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                detail = json.loads(raw).get("detail", {})
            except Exception:
                detail = {"code": "http_%d" % e.code, "message": raw[:200]}
            if isinstance(detail, str):
                detail = {"code": detail, "message": ""}
            raise SteveError(detail.get("code", "http_%d" % e.code),
                            detail.get("message", ""), e.code) from None

    def _maybe_refresh(self):
        if self.token and time.time() > self.token_exp - 60:
            try:
                self.get_token()
            except SteveError:
                pass  # pending_confirmation etc.: caller handles

    # ------------------------------------------------------------ calls --
    def get_keys(self):
        req = urllib.request.Request(self.base + "/keys", method="GET",
                                    headers={"Accept": "application/json"})
        return self._send(req)

    def enroll(self, code, public_key_b64, name, version, catalog):
        body = crypto.canonical_json({"code": code, "public_key": public_key_b64,
                                     "name": name, "version": version,
                                     "catalog": catalog})
        # sign exactly the bytes we send
        headers = crypto.sign_request(self.sk, "POST",
                                     self.base_path + "/enroll", "", body)
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + "/enroll", data=body,
                                    method="POST", headers=headers)
        return self._send(req)

    def get_token(self):
        out = self._request("POST", "/token", auth=False)
        self.token = out["token"]
        # refresh well before expiry (900 s typical)
        self.token_exp = time.time() + float(out.get("expires_in", 900)) - 120
        return out

    def put_catalog(self, catalog):
        return self._request("PUT", "/catalog",
                             body=crypto.canonical_json(catalog),
                             media="application/json")

    def messages(self, after, wait=30):
        return self._request("GET", "/messages",
                             query="after=%d&wait=%d" % (after, wait))

    def report_run(self, run_id, state, **kw):
        body = {"state": state}
        for k in ("progress", "message", "result", "error"):
            if kw.get(k) is not None:
                body[k] = kw[k]
        return self._request("POST", "/runs/%s" % run_id,
                             body=crypto.canonical_json(body),
                             media="application/json")

    def put_file(self, run_id, name, data: bytes, media):
        return self._request("PUT", "/runs/%s/files/%s" % (run_id, name),
                             body=data, media=media)

    def post_event(self, name, data):
        return self._request("POST", "/events",
                            body=crypto.canonical_json({"name": name,
                                                       "data": data}),
                            media="application/json")

    def put_panel(self, name, title, placement, files):
        return self._request("PUT", "/panels/%s" % name,
                            body=crypto.canonical_json(
                                {"title": title, "placement": placement,
                                 "files": files}),
                            media="application/json")

    def download(self, url, headers=None):
        """Fetch a STEVE input file (one-time ticket: plain GET + headers)."""
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise SteveError("download_failed", "HTTP %d" % e.code, e.code) \
                from None
