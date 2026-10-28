#!/bin/bash
# Download CRA's information return schemas into .cra/ (never committed). The tests read them from there.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cra/zip
if [[ -n "${CRA_SCHEMA_URL:-}" ]]; then
  urls=("$CRA_SCHEMA_URL")
else
  urls=(
    "https://www.canada.ca/content/dam/cra-arc/serv-info/eservices/xmlschm1-26-3.zip"
    "https://www.canada.ca/content/dam/cra-arc/serv-info/eservices/xmlschm1-27-1.zip"
  )
fi
for url in "${urls[@]}"; do
  curl -fsSL "$url" -o ".cra/zip/$(basename "$url")"
  unzip -tq ".cra/zip/$(basename "$url")"
  echo "Saved .cra/zip/$(basename "$url")"
done
