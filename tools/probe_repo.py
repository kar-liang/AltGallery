#!/usr/bin/env python3
"""Probe GitHub repos for AltStore-source viability.

For each repo, report whether its Releases ship an .ipa asset, which asset
matches, and a suggested `asset_pattern` regex. Stdlib only.

Usage:
    python tools/probe_repo.py owner/repo [owner/repo ...]
    python tools/probe_repo.py --file repos.txt
    python tools/probe_repo.py --json owner/repo

Auth: pass --token, or set GITHUB_TOKEN, to avoid the 60 req/h anonymous limit.
Proxy: set HTTPS_PROXY if github.com is slow or unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "altgallery-probe/1.0"


def parse_repo(text: str) -> str | None:
    """Accept owner/repo, a github.com URL, or a URL with a trailing path."""
    text = text.strip()
    if not text:
        return None
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", text)
    if m:
        owner, name = m.group(1), m.group(2)
    else:
        m = re.fullmatch(r"([\w.-]+)/([\w.-]+)", text)
        if not m:
            return None
        owner, name = m.group(1), m.group(2)
    if name.endswith(".git"):
        name = name[:-4]
    return f"{owner}/{name}"


def api_get(url: str, token: str | None) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001 - network layer, report and move on
        print(f"    ! request failed: {exc}", file=sys.stderr)
        return 0, None


def probe(repo: str, token: str | None, include_prerelease: bool) -> dict:
    result: dict = {"repo": repo, "ok": False, "reason": "", "releases": [], "asset_pattern": "", "assets": []}

    status, meta = api_get(f"{API}/repos/{repo}", token)
    if status != 200 or not isinstance(meta, dict):
        result["reason"] = f"repo lookup failed (HTTP {status})"
        return result
    result["description"] = meta.get("description") or ""
    result["archived"] = bool(meta.get("archived"))
    result["license"] = (meta.get("license") or {}).get("spdx_id") or "none"

    status, releases = api_get(f"{API}/repos/{repo}/releases?per_page=8", token)
    if status != 200 or not isinstance(releases, list):
        result["reason"] = f"releases lookup failed (HTTP {status})"
        return result
    if not releases:
        result["reason"] = "no releases at all (source-only project? needs manual build)"
        return result

    picked = None
    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prerelease:
            continue
        ipas = [a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".ipa")]
        if ipas:
            picked = (rel, ipas)
            break

    if not picked:
        # Report what the latest release does ship, so the cause is obvious.
        latest = releases[0]
        names = [a.get("name", "") for a in latest.get("assets", [])] or ["<no assets>"]
        result["reason"] = f"no .ipa asset in recent releases (latest {latest.get('tag_name')}: {', '.join(names[:4])})"
        return result

    rel, ipas = picked
    tag = rel.get("tag_name") or ""
    result["ok"] = True
    result["tag"] = tag
    result["published_at"] = (rel.get("published_at") or "")[:10]
    result["assets"] = [{"name": a["name"], "size": a.get("size"), "downloads": a.get("download_count")} for a in ipas]

    # Suggest a regex that pins the first ipa asset. Escape dots, keep it exact
    # when the name carries the version so future releases still match.
    name = ipas[0]["name"]
    stem = re.sub(r"\d+(\.\d+)+", "<VER>", name)
    if "<VER>" in stem:
        prefix = re.escape(stem.split("<VER>")[0])
        suffix = re.escape(stem.split("<VER>")[-1])
        pattern = prefix + r".*" + suffix
    else:
        pattern = re.escape(name)
    result["asset_pattern"] = pattern
    result["strip_v_prefix"] = tag.lstrip("vV") != tag
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="*")
    ap.add_argument("--file", help="file with one repo per line")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--prerelease", action="store_true", help="allow prerelease versions")
    args = ap.parse_args()

    raw = list(args.repos)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            raw += [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    repos = [r for r in (parse_repo(x) for x in raw) if r]
    if not repos:
        ap.error("no valid repo given")

    out = []
    for repo in repos:
        res = probe(repo, args.token, args.prerelease)
        out.append(res)
        if args.json:
            continue
        if res["ok"]:
            print(f"OK    {repo}  ->  {res['tag']}  ({res['published_at']})")
            for a in res["assets"]:
                print(f"        ipa: {a['name']}  {a['size']} B  dl={a['downloads']}")
            print(f"        asset_pattern = \"{res['asset_pattern']}\"")
            if res["archived"]:
                print("        ! repo is ARCHIVED")
        else:
            print(f"SKIP  {repo}  --  {res['reason']}")

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))

    ok = sum(1 for r in out if r["ok"])
    print(f"\n{ok}/{len(out)} usable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
