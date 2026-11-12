#!/usr/bin/env python3
"""Create an AltGallery app entry from a GitHub repo.

Given owner/repo, this script:
  1. probes Releases for a usable .ipa asset
  2. downloads it and reads the real bundle id / min OS / display name
  3. fetches the best available icon (repo artwork first, ipa as fallback)
  4. writes apps/<Name>/{config.toml,news.toml,icon.png}

It never touches other apps and never commits. Run it from the repo root:

    python tools/add_app.py owner/repo
    python tools/add_app.py --repo owner/repo --force

Exit codes: 0 added/updated, 2 unusable repo (reason on stdout), 1 hard error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UA = "altgallery-add-app/1.0"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TINT = "#3B82F6"
MAX_IPA_BYTES = 400 * 1024 * 1024


def api(url: str, token: str | None) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001
        return 0, None


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as fh:
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IPA_BYTES:
                raise RuntimeError(f"ipa larger than {MAX_IPA_BYTES} bytes")
            fh.write(chunk)
    return total


def raw(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:  # noqa: BLE001
        return None


def probe(repo: str, token: str | None) -> dict:
    """Same rules as probe_repo.py: first release with an .ipa asset wins."""
    out: dict = {"ok": False, "reason": "", "repo": repo}
    status, meta = api(f"{API}/repos/{repo}", token)
    if status != 200 or not isinstance(meta, dict):
        out["reason"] = f"仓库读取失败 (HTTP {status})，可能不存在或拼错"
        return out
    out["description"] = (meta.get("description") or "").strip()
    out["archived"] = bool(meta.get("archived"))
    out["default_branch"] = meta.get("default_branch") or "main"
    out["html_url"] = meta.get("html_url") or f"https://github.com/{repo}"

    status, releases = api(f"{API}/repos/{repo}/releases?per_page=10", token)
    if status != 200 or not isinstance(releases, list):
        out["reason"] = f"Release 列表读取失败 (HTTP {status})"
        return out
    if not releases:
        out["reason"] = "这个仓库没有任何 Release，纯源码项目加不了（需要自己编译出 ipa）"
        return out

    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        ipas = [a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".ipa")]
        if ipas:
            ipas.sort(key=lambda a: a.get("size") or 0, reverse=True)
            out.update(
                ok=True,
                tag=rel.get("tag_name") or "",
                published_at=(rel.get("published_at") or "")[:10],
                asset=ipas[0]["name"],
                asset_url=ipas[0]["browser_download_url"],
                asset_size=ipas[0].get("size") or 0,
                extra_assets=[a["name"] for a in ipas[1:]],
            )
            return out

    latest = releases[0]
    names = [a.get("name", "") for a in latest.get("assets", [])] or ["<没有资产>"]
    out["reason"] = f"最近的 Release 里没有 .ipa（{latest.get('tag_name')} 只有：{', '.join(names[:3])}）"
    return out


def suggest_pattern(asset: str) -> str:
    stem = re.sub(r"\d+(\.\d+)+", "<VER>", asset)
    if "<VER>" in stem:
        head, tail = stem.split("<VER>")[0], stem.split("<VER>")[-1]
        return re.escape(head) + ".*" + re.escape(tail) + "$"
    return re.escape(asset) + "$"


def pick_icon(repo_info: dict, ipa: Path, token: str | None, work: Path) -> tuple[Path | None, str]:
    """Try repo artwork (>=512px) first; fall back to the ipa's largest loose icon."""
    owner_repo = repo_info["repo"]
    branch = repo_info["default_branch"]
    base = f"https://raw.githubusercontent.com/{owner_repo}/{branch}/"

    candidates = [
        "ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json",
        "Runner/Assets.xcassets/AppIcon.appiconset/Contents.json",
        "Assets.xcassets/AppIcon.appiconset/Contents.json",
    ]
    for manifest in candidates:
        data = raw(base + manifest)
        if not data:
            continue
        try:
            spec = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        best = None
        best_px = 0
        for img in spec.get("images", []):
            if not img.get("filename"):
                continue
            try:
                px = int(float(img["size"].split("x")[0])) * int(img.get("scale", "1x").rstrip("x"))
            except Exception:  # noqa: BLE001
                continue
            if px > best_px:
                best, best_px = img["filename"], px
        if best and best_px >= 512:
            blob = raw(base + manifest.rsplit("/", 1)[0] + "/" + best)
            if blob and blob[:8] == b"\x89PNG\r\n\x1a\n":
                dest = work / "icon.png"
                dest.write_bytes(blob)
                return dest, f"repo {best} ({best_px}px)"

    # Tauri / misc single-file icons
    for guess in ("src-tauri/icons/icon.png", "icon.png", "assets/icon.png", "AppIcon.png"):
        blob = raw(base + guess)
        if blob and blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) > 3000:
            dest = work / "icon.png"
            dest.write_bytes(blob)
            return dest, f"repo {guess}"

    # ipa fallback
    dest = work / "icon.png"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ipa_icon.py"), str(ipa), "--out", str(dest)],
        capture_output=True, text=True,
    )
    if dest.exists():
        m = re.search(r"\((\d+)x(\d+)", proc.stdout + proc.stderr)
        px = f" {m.group(1)}px" if m else ""
        return dest, f"ipa{px} (低清，建议手动换)"
    return None, "无"


def sample_tint(icon: Path | None) -> str:
    if icon is None:
        return DEFAULT_TINT
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from render_news import extract_icon_color  # type: ignore

        return extract_icon_color(icon)
    except Exception:  # noqa: BLE001
        return DEFAULT_TINT


def safe_dir_name(name: str, fallback: str = "") -> str:
    """A filesystem-safe folder name. Keep ASCII alnum only.

    Many apps ship a CJK display name (e.g. 全局刷新) which strips down to
    nothing — fall back to the repo name instead of a generic "App", otherwise
    every Chinese-named app would collide in the same folder.
    """
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", name)
    if cleaned:
        return cleaned
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", fallback)
    return cleaned or "App"


def toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_config(info: dict, app: dict) -> str:
    pattern = suggest_pattern(info["asset"])
    strip_v = info["tag"].lstrip("vV") != info["tag"]
    shots = ""
    desc = (info.get("description") or "").strip()
    if len(desc) < 12:
        desc = f"{app['name']} — 来自 {info['repo']} 的 iOS 应用。"
    icon_url = app["icon_url"]
    lines = [
        f"# altgen config for the {app['name']} AltStore source.",
        "# Generated by tools/add_app.py — edit freely, then re-run altgen.",
        "",
        "[github]",
        f"repo = {toml_str(info['repo'])}",
        "",
        "[source]",
        f"name = {toml_str(app['name'])}",
        f"subtitle = {toml_str(app['name'] + ' AltStore 源')}",
        f"description = {toml_str('Auto-updated AltStore source for ' + app['name'])}",
        f"icon_url = {toml_str(icon_url)}",
        f"website = {toml_str(info['html_url'])}",
        f"tint_color = {toml_str(app['tint'])}",
        "",
        "[app]",
        f"name = {toml_str(app['name'])}",
        f"bundle_identifier = {toml_str(app['bundle_id'])}",
        f"developer_name = {toml_str(info['repo'].split('/')[0])}",
        f"subtitle = {toml_str(desc[:120])}",
        f'description = """{desc}"""',
        f"icon_url = {toml_str(icon_url)}",
        "screenshots = []",
        f"tint_color = {toml_str(app['tint'])}",
        f"min_os_version = {toml_str(app['min_os'])}",
        "",
        "[versions]",
        f"strip_v_prefix = {'true' if strip_v else 'false'}",
        "include_prereleases = false",
        f"asset_pattern = {toml_str(pattern)}",
        "",
        "[news]",
        'title_template = "{name} {version} · {date}"',
        f"image_url = {toml_str(app['news_url'])}",
        "",
        "[output]",
        'path = "apps.json"',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="owner/repo or a github URL")
    ap.add_argument("--repo", dest="repo_opt")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing app dir")
    ap.add_argument("--raw-prefix", default=None,
                    help="URL prefix for icons, default https://raw.githubusercontent.com/<user>/<repo>/refs/heads/master/")
    args = ap.parse_args()

    target = args.repo_opt or args.target or ""
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s#?]+)", target) or re.fullmatch(r"([\w.-]+)/([\w.-]+)", target.strip())
    if not m:
        print("ERROR 给的不是 GitHub 仓库地址")
        return 2
    repo = f"{m.group(1)}/{m.group(2)}".removesuffix(".git")

    info = probe(repo, args.token)
    if not info["ok"]:
        print(f"UNUSABLE {repo} :: {info['reason']}")
        return 2

    print(f"FOUND {repo} -> {info['tag']} ({info['published_at']}) {info['asset']} "
          f"{round(info['asset_size'] / 1048576, 1)}MB")
    if info.get("extra_assets"):
        print(f"NOTE  同版本还有其它 ipa，已选最大的那个: {', '.join(info['extra_assets'][:3])}")

    work = Path(tempfile.mkdtemp(prefix="addapp-"))
    try:
        ipa = work / "app.ipa"
        size = download(info["asset_url"], ipa)
        print(f"FETCH ipa {round(size / 1048576, 1)}MB")

        meta = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "ipa_bundle_id.py"), str(ipa), "--json"],
            capture_output=True, text=True,
        )
        if meta.returncode != 0:
            print(f"UNUSABLE {repo} :: ipa 读不出 Info.plist\n{meta.stderr[:300]}")
            return 2
        plist = json.loads(meta.stdout)
        bundle_id = plist.get("bundle_id") or ""
        if not bundle_id or bundle_id.startswith("com.example."):
            print(f"UNUSABLE {repo} :: ipa 的 bundle id 不可靠（{bundle_id or '空'}）")
            return 2
        app_name = (plist.get("name") or repo.split("/")[1]).strip()
        min_os = plist.get("min_os_version") or "14.0"
        version = plist.get("version") or info["tag"].lstrip("vV")
        print(f"INFO  name={app_name} bundle={bundle_id} version={version} minOS={min_os}")

        dir_name = safe_dir_name(app_name, repo.split("/")[-1])
        app_dir = ROOT / "apps" / dir_name
        if app_dir.exists() and not args.force:
            existing = (app_dir / "config.toml").read_text(encoding="utf-8")
            found = re.search(r'^repo\s*=\s*"([^"]+)"', existing, re.M)
            old = (found.group(1) if found else "").strip()
            if old.lower() == repo.lower():
                print(f"ALREADY {repo} 已经在 apps/{dir_name} 里，这次不改动")
                return 0
            print(f"UNUSABLE {repo} :: apps/{dir_name} 已被 {old or '别的项目'} 占用")
            return 2

        icon, icon_src = pick_icon(info, ipa, args.token, work)
        tint = sample_tint(icon)
        print(f"ICON  {icon_src} -> tint {tint}")

        prefix = args.raw_prefix
        if not prefix:
            repo_slug = os.environ.get("GITHUB_REPOSITORY", "kar-liang/AltGallery")
            prefix = f"https://raw.githubusercontent.com/{repo_slug}/refs/heads/master/"
        app = {
            "name": app_name,
            "bundle_id": bundle_id,
            "min_os": min_os,
            "tint": tint,
            "icon_url": f"{prefix}apps/{dir_name}/icon.png",
            "news_url": f"{prefix}apps/{dir_name}/images/news.png",
        }

        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "images").mkdir(exist_ok=True)
        if icon is not None:
            shutil.copyfile(icon, app_dir / "icon.png")
        (app_dir / "config.toml").write_text(build_config(info, app), encoding="utf-8")
        # Tagline: first sentence, cut on a word boundary — a hard slice mid-word
        # looks broken on the news card ("for iO").
        desc = (info.get("description") or "").strip()
        tagline = desc.split(".")[0].strip() if desc else ""
        if len(tagline) > 34:
            tagline = tagline[:34].rsplit(" ", 1)[0].rstrip(",;:")
        if not tagline:
            tagline = "v" + version
        (app_dir / "news.toml").write_text(
            "# render_news.py config: python3 tools/render_news.py --out apps/%s\n"
            'name = %s\ntagline = %s\n\n[colors]\n'
            % (dir_name, toml_str(app_name), toml_str(tagline)),
            encoding="utf-8",
        )

        print(f"WROTE apps/{dir_name}/config.toml")
        print(f"SUMMARY {app_name}|{bundle_id}|{version}|{min_os}|apps/{dir_name}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
