# BRAVIA 3.0 WEB profiles (fork of Dictionarry-Hub/trash-pcd)

This repo is TRaSH Guides' Profilarr database (`trash-pcd`) plus **one extra op**,
`ops/100000.bravia-web-profiles.sql`. It adds two quality profiles for Radarr and Sonarr,
aimed at Plex direct play on a Sony BRAVIA Google TV → eARC → Marantz Cinema 70s with 3.0 speakers:

- `WEB-2160p (BRAVIA 3.0)`: WEBDL/WEBRip-2160p only, stops upgrading at WEB 2160p
- `WEB-1080p (BRAVIA 3.0)`: WEBDL/WEBRip-1080p only, stops upgrading at WEB 1080p

Profilarr applies ops in numeric order, so op 100000 always runs after every TRaSH op. It copies
TRaSH's `WEB-2160p` / `WEB-1080p` **at apply time** (qualities, languages, every score), then
applies the overrides below. Upstream tier and group changes therefore flow straight into the
BRAVIA profiles. Min score 0, upgrade-until score 10000, increment 1 (TRaSH defaults).

| File | What it is |
|---|---|
| `ops/100000.bravia-web-profiles.sql` | The config: 1 regex, 2 custom formats, 2 profiles. Generated, don't hand-edit |
| `bravia/build_op.py` | Source of the op. Scores live in `OVERRIDES` |
| `bravia/validate.sh` | Builds the repo the way Profilarr does, applies the op strictly, checks integrity, dry-runs. `--regen` regenerates the op first |
| `bravia/dryrun.py` | Scores release titles against a profile via the `profilarr-parser` sidecar (the .NET parser and regex engine) |
| `bravia/titles-*.txt` | Sample releases for the dry run |

## Scores (same on the Radarr and Sonarr sides of both profiles)

| Custom format | Score | Source | Notes |
|---|---:|---|---|
| DD+ ATMOS | +2000 | TRaSH | E-AC-3 JOC |
| DV Boost | +1500 | TRaSH | Any DV title: WEB Profile 5 and Profile 8 |
| HDR10 | +500 | TRaSH | TRaSH's catch-all "HDR" (renamed in trash-pcd). Also matches DV HDR10, so P8 (DV + HDR10 fallback) scores 2000 and P5 scores 1500 |
| DTS | +500 | TRaSH | DTS core only. DTS-HD MA / DTS:X / HRA / ES stay at 0 |
| Repack/Proper, Repack2, Repack3 | +10 / +11 / +12 | TRaSH | Kept in step so a Repack2 still beats a Repack |
| AAC (Multichannel) | −1500 | **custom** | AAC + 5.x/6.x/7.x, not DD/DD+/DTS/TrueHD/FLAC/PCM. AAC 2.0 is unaffected |
| DV FEL (Profile 7) | −10000 | **custom** | DV + Blu-ray or BR-DISK source (Remuxes and Blu-ray encodes) |
| DV (Disk) | −10000 | TRaSH | FraMeSToR P7 remuxes |
| TrueHD, TrueHD ATMOS | −10000 | TRaSH | |
| x265 (HD) | −10000 | TRaSH | Only matches ≤1080p by design |
| Retags, Obfuscated | −10000 | TRaSH | Bad re-tags |
| Everything else | TRaSH default | TRaSH | WEB tiers 1600–1700; LQ, LQ (Release Title), Upscaled, BR-DISK, AV1, 3D, Generated Dynamic HDR, x265 (no HDR/DV), Bad Dual Groups and Extras at −10000; streaming services |

Not scored on purpose: `DV (w/o HDR fallback)` (P5 would otherwise score twice) and
`HDR10+ Boost` (Sony TVs don't support HDR10+).

Custom format definitions (all conditions `arr_type = all`):

- **DV FEL (Profile 7)**: release title matches `Dolby Vision` (required) **and** source is
  Bluray or BR-DISK (either).
- **AAC (Multichannel)**: TRaSH `AAC` conditions plus a required title match on the new regex
  `Multichannel (5.1-7.1)` = `[^0-9][5-7][ .][0-1]\b`.

## Changing a score

```bash
cd /opt/arr-stack/profilarr/trash-pcd-bravia
$EDITOR bravia/build_op.py                 # OVERRIDES table
./bravia/validate.sh --regen               # regenerate op, validate, dry run
git commit -am "bravia: <what changed>" && git push
```

Then in Profilarr: Databases → `Trash Guides (BRAVIA)` → pull/sync (or wait for the hourly auto-pull),
then sync the Radarr/Sonarr instances.

## Pulling in TRaSH updates

```bash
cd /opt/arr-stack/profilarr/trash-pcd-bravia
git fetch upstream && git merge --ff-only upstream/main || git merge upstream/main
./bravia/validate.sh                       # must still pass
git push
```

Upstream never touches `ops/100000.*` or `bravia/`, so merges don't conflict. If TRaSH removes
a custom format named in `OVERRIDES`, that override is skipped rather than breaking the build.

## Commands

```bash
# Validate + dry run
./bravia/validate.sh

# Dry-run your own titles (one per line) against one profile
./bravia/validate.sh --no-dryrun && python3 -I bravia/dryrun.py bravia/.build/test.db 'WEB-2160p (BRAVIA 3.0)' radarr my-titles.txt

# Confirm what landed in Radarr after a sync (Sonarr: port 8989, ~/.config/Sonarr)
KEY=$(grep -oP '(?<=<ApiKey>)[^<]+' ~/.config/Radarr/config.xml)
curl -s -H "X-Api-Key: $KEY" http://127.0.0.1:7878/api/v3/qualityprofile | python3 -c '
import json,sys
for p in json.load(sys.stdin):
    if "BRAVIA" in p["name"]:
        print(p["name"], "min", p["minFormatScore"], "cutoffScore", p["cutoffFormatScore"])
        for f in sorted(p["formatItems"], key=lambda f: -abs(f["score"])):
            if f["score"]: print("  %7d  %s" % (f["score"], f["name"]))'
```

## Things to know

- **P5 vs P8 can't be told apart exactly from a release name.** On WEB, `DV` alone is
  usually P5 and `DV HDR`/`DV HDR10` is P8. Profile 7 only comes from Blu-ray sources, so it's
  blocked twice: these profiles only allow WEB qualities, and `DV FEL (Profile 7)` scores −10000
  if Blu-ray qualities are ever enabled.
- **P5 has no fallback.** Any other client that can't do DV (e.g. Jellyfin clients) will show
  green/purple video. That's why TRaSH scores `DV (w/o HDR fallback)` at −10000 by default.
  It's kept positive here because the BRAVIA is the target.
- **3.0 speakers:** Atmos gives no height or surround benefit, because the Marantz folds it into
  L/C/R. Preferring DD+ Atmos is harmless, but at +2000 audio outweighs the WEB group tiers.
- **AAC 5.1 at −1500 with min score 0** is effectively a reject, unless a WEB Tier 01 group
  (+1700) offsets it.
- **TrueHD almost never appears on WEB releases**, so that block mostly matters if Blu-ray
  tiers are enabled later.
- DTS-HD MA / DTS:X passthrough on the Sony app wasn't tested, so they're left neutral (0).
- `dryrun.py` skips language-based formats (`Language: Not Original`, Sonarr only) because it
  needs metadata. Profilarr's Testing page and the *arr apply them normally.
- This database and Dictionarry share 46 custom format names (TrueHD, DTS, AAC, …) with
  different definitions. Don't sync profiles from both to the same Radarr/Sonarr.
