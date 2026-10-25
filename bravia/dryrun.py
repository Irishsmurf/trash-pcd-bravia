#!/usr/bin/env python3
"""Dry-run a Profilarr profile against release titles, using the profilarr-parser sidecar.

Parsing (source/resolution/group) and every regex run in the parser's .NET engine,
so matching behaves like Radarr/Sonarr. CF logic follows the *arr rules: conditions
are grouped by type; within a group all required ones must pass and at least one must pass.

Usage: python3 -I dryrun.py <compiled.db> <profile name> <radarr|sonarr> <titles.txt>
"""
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict

SKIP_TYPES = {"language", "indexer_flag", "release_type", "size", "year"}  # need metadata we don't have
SOURCE_MAP = {"WebDL": "web_dl", "WebRip": "webrip", "Bluray": "bluray", "BlurayRaw": "bluray_raw",
              "DVD": "dvd", "Television": "television"}


def parser(path, body):
    r = subprocess.run(["docker", "exec", "-i", "profilarr", "curl", "-s", "-X", "POST",
                        f"http://profilarr-parser:5000{path}", "-H", "Content-Type: application/json",
                        "--data-binary", "@-"], input=json.dumps(body), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def quality_name(p):
    src, res, mod = p.get("source"), p.get("resolution"), p.get("modifier")
    if mod == "Remux":
        return f"Remux-{res}p"
    if src == "BlurayRaw" or mod == "BRDISK":
        return "BR-DISK"
    return {"WebDL": f"WEBDL-{res}p", "WebRip": f"WEBRip-{res}p", "Bluray": f"Bluray-{res}p",
            "Television": f"HDTV-{res}p"}.get(src, "Unknown")


def main(db_path, profile, arr, titles_path):
    db = sqlite3.connect(db_path)
    titles = [t.strip() for t in open(titles_path) if t.strip() and not t.startswith("#")]
    kind = "movie" if arr == "radarr" else "series"

    scores = dict(db.execute("select custom_format_name, score from quality_profile_custom_formats "
                             "where quality_profile_name=? and arr_type=?", (profile, arr)))
    allowed = {r[0] for r in db.execute(
        "select coalesce(m.quality_name, pq.quality_name) from quality_profile_qualities pq "
        "left join quality_group_members m on m.quality_profile_name=pq.quality_profile_name "
        "and m.quality_group_name=pq.quality_group_name where pq.quality_profile_name=? and pq.enabled=1", (profile,))}
    min_score = db.execute("select minimum_custom_format_score from quality_profiles where name=?", (profile,)).fetchone()[0]

    conds = defaultdict(list)  # cf -> [(type, negate, required, kind, value)]
    skipped = set()
    for cf, name, ctype, carr, neg, req in db.execute(
            "select custom_format_name, name, type, arr_type, negate, required from custom_format_conditions"):
        if cf not in scores or carr not in ("all", arr):
            continue
        if ctype in SKIP_TYPES:
            skipped.add(cf)
            continue
        val = None
        if ctype in ("release_title", "release_group", "edition"):
            val = db.execute("select r.pattern from condition_patterns p join regular_expressions r "
                             "on r.name=p.regular_expression_name where p.custom_format_name=? and p.condition_name=?",
                             (cf, name)).fetchone()[0]
        elif ctype == "source":
            val = db.execute("select source from condition_sources where custom_format_name=? and condition_name=?", (cf, name)).fetchone()[0]
        elif ctype == "resolution":
            val = db.execute("select resolution from condition_resolutions where custom_format_name=? and condition_name=?", (cf, name)).fetchone()[0]
        elif ctype == "quality_modifier":
            val = db.execute("select quality_modifier from condition_quality_modifiers where custom_format_name=? and condition_name=?", (cf, name)).fetchone()[0]
        conds[cf].append((ctype, neg, req, val))
    for cf in skipped:
        conds.pop(cf, None)

    parsed = {t: parser("/parse", {"title": t, "type": kind}) for t in titles}
    patterns = sorted({v for cl in conds.values() for (ct, _, _, v) in cl if ct in ("release_title", "release_group", "edition")})
    texts = sorted(set(titles) | {p.get("releaseGroup") or "" for p in parsed.values()} - {""})
    matches = parser("/match/batch", {"texts": texts, "patterns": patterns})["results"]

    print(f"\n### {profile} [{arr}]   min score {min_score}"
          + (f"   (not evaluated here: {', '.join(sorted(skipped))})" if skipped else ""))
    for t in titles:
        p = parsed[t]
        grp = p.get("releaseGroup") or ""
        hit = []
        for cf, cl in conds.items():
            groups = defaultdict(list)
            for ctype, neg, req, val in cl:
                if ctype == "release_title":
                    m = matches[t][val]
                elif ctype == "release_group":
                    m = bool(grp) and matches[grp][val]
                elif ctype == "source":
                    m = SOURCE_MAP.get(p.get("source")) == val
                elif ctype == "resolution":
                    m = f"{p.get('resolution')}p" == val
                elif ctype == "quality_modifier":
                    m = (p.get("modifier") or "").lower() == val
                else:
                    m = False
                groups[ctype].append((m != bool(neg), req))
            if all(not any(r and not ok for ok, r in g) and any(ok for ok, _ in g) for g in groups.values()):
                hit.append(cf)
        total = sum(scores[c] for c in hit)
        qn = quality_name(p)
        verdict = "REJECT (quality)" if qn not in allowed else ("REJECT (score)" if total < min_score else "accept")
        shown = ", ".join(f"{c} {scores[c]:+d}" for c in sorted(hit, key=lambda c: -abs(scores[c])) if scores[c])
        print(f"{total:>7}  {verdict:<16} {qn:<13} {t}\n{'':>9}{shown}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
