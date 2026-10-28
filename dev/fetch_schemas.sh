#!/bin/bash
# Download CRA's information return schemas into .cra/ (never committed). The tests read them from there.
set -euo pipefail
cd "$(dirname "$0")/.."
url="${CRA_SCHEMA_URL:-https://www.canada.ca/content/dam/cra-arc/serv-info/eservices/xmlschm1-27-1.zip}"
mkdir -p .cra/zip
curl -fsSL "$url" -o ".cra/zip/$(basename "$url")"
unzip -tq ".cra/zip/$(basename "$url")"
echo "Saved .cra/zip/$(basename "$url")"
