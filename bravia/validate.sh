#!/usr/bin/env bash
# Build this repo exactly as Profilarr does (schema ops, then ops/ in numeric order),
# with ops/100000.bravia-web-profiles.sql applied strictly (stop on first error),
# check integrity, then dry-run sample releases through the profilarr-parser sidecar.
#   ./bravia/validate.sh          validate the committed op
#   ./bravia/validate.sh --regen  regenerate the op from build_op.py first
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
OP="$REPO/ops/100000.bravia-web-profiles.sql"
B="$HERE/.build"
mkdir -p "$B" && rm -f "$B"/*.db

if [[ "${1:-}" == "--regen" ]]; then
  python3 -I "$HERE/build_op.py" > "$OP"
  echo "== regenerated $(basename "$OP")"
fi

SCHEMA_VER=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dependencies"]["https://github.com/Dictionarry-Hub/schema"])' "$REPO/pcd.json")
if [[ ! -d "$B/schema-$SCHEMA_VER" ]]; then
  git clone -q --depth 1 --branch "$SCHEMA_VER" https://github.com/Dictionarry-Hub/schema "$B/schema-$SCHEMA_VER"
fi

echo "== build upstream ops ($(git -C "$REPO" log -1 --format='%h %s'))"
{
  echo "PRAGMA foreign_keys=ON; PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; BEGIN;"
  for f in $(ls "$B/schema-$SCHEMA_VER"/ops/*.sql | sort -V); do cat "$f"; echo ";"; done
  for f in $(ls "$REPO"/ops/*.sql | xargs -n1 basename | sort -n); do
    [[ "$REPO/ops/$f" == "$OP" ]] || { cat "$REPO/ops/$f"; echo ";"; }
  done
  echo "COMMIT;"
} | sqlite3 "$B/trash.db" >/dev/null

echo "== apply $(basename "$OP")"
cp "$B/trash.db" "$B/test.db"
{ echo "PRAGMA foreign_keys=ON; BEGIN;"; cat "$OP"; echo "COMMIT;"; } | sqlite3 -bail "$B/test.db"
[[ -z "$(sqlite3 "$B/test.db" 'PRAGMA foreign_key_check;')" ]] || { echo "FK check failed"; exit 1; }
[[ "$(sqlite3 "$B/test.db" 'PRAGMA integrity_check;')" == ok ]] || { echo "integrity check failed"; exit 1; }
n=$(sqlite3 "$B/test.db" "select count(*) from quality_profiles where name like '%BRAVIA%'")
[[ "$n" == 2 ]] || { echo "expected 2 BRAVIA profiles, got $n"; exit 1; }
echo "OK: op applies cleanly, 2 profiles"

[[ "${2:-${1:-}}" == "--no-dryrun" ]] && exit 0
echo "== dry run"
for p in 'WEB-2160p (BRAVIA 3.0)' 'WEB-1080p (BRAVIA 3.0)'; do
  python3 -I "$HERE/dryrun.py" "$B/test.db" "$p" radarr "$HERE/titles-movies.txt"
  python3 -I "$HERE/dryrun.py" "$B/test.db" "$p" sonarr "$HERE/titles-series.txt"
done
