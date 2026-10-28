#!/bin/bash
# Build the module README.rst and static/description/index.html from the readme/ fragments.
set -euo pipefail
cd "$(dirname "$0")/../l10n_ca_contractor_slips"
{
  printf '===================\nT4A and T5018 Slips\n===================\n\n'
  printf 'License: LGPL-3\n\n'
  pandoc -f gfm -t rst readme/DESCRIPTION.md
  printf '\n**Table of contents**\n\n.. contents::\n   :local:\n\n'
  for part in CONFIGURE:Configuration USAGE:Usage ROADMAP:"Known issues / Roadmap" CONTRIBUTORS:Contributors; do
    file="${part%%:*}"; title="${part#*:}"
    printf '%s\n%s\n\n' "$title" "$(printf '%*s' ${#title} '' | tr ' ' '-')"
    pandoc -f gfm -t rst "readme/$file.md"
    printf '\n'
  done
  printf 'Maintainers\n-----------\n\nThis module is maintained by Solvync Inc.\n'
} > README.rst
mkdir -p static/description
# A fragment rather than a full page: Odoo's sanitizer drops a standalone page's style block. The
# store page leaves out the table of contents, which pandoc cannot render from the directive.
grep -v -e '^\*\*Table of contents\*\*$' -e '^\.\. contents::$' -e '^   :local:$' README.rst \
  | pandoc -f rst -t html5 -o static/description/index.html
# The store page also carries the screens. They stay out of README.rst, whose text is the module
# description the translation files are keyed on, and go in ahead of "Before you file".
if [[ -f readme/SCREENS.md ]]; then
  pandoc -f gfm -t html5 readme/SCREENS.md > static/description/.screens.html
  python3 - <<'PY'
from pathlib import Path
page = Path("static/description/index.html")
screens = Path("static/description/.screens.html")
html = page.read_text()
marker = '<h2 id="before-you-file">'
if marker not in html:
    raise SystemExit("index.html has no Before you file heading to place the screens ahead of")
# img-fluid keeps each screen inside the page width on the store and in the Apps form.
block = screens.read_text().replace("<img ", '<img class="img-fluid" ')
page.write_text(html.replace(marker, block + marker, 1))
screens.unlink()
PY
fi
# Keep visible release facts and their microdata in the generated store description.
python3 - <<'PYSCHEMA'
import ast
from html import escape
from pathlib import Path
manifest = ast.literal_eval(Path("__manifest__.py").read_text())
version = manifest["version"]
major = version.split(".")[0]
page = Path("static/description/index.html")
html = page.read_text()
html = html.replace('<h1 id="t4a-and-t5018-slips">', '<h1 itemprop="name" id="t4a-and-t5018-slips">', 1)
facts = f'''<section class="mb-4">
<h2>Release details</h2>
<p>Version <span itemprop="softwareVersion">{escape(version)}</span>, stable release.</p>
<p>Server operating system: <span itemprop="operatingSystem">Linux</span>.</p>
<p itemprop="softwareRequirements">Requires Odoo {escape(major)} Community or Enterprise, on Odoo.sh or your own server. Odoo Online is not supported.</p>
<p><span itemprop="offers" itemscope="" itemtype="https://schema.org/Offer">Module price: <span itemprop="price">0</span> <span itemprop="priceCurrency">CAD</span> (free).</span> Hosting, Odoo subscriptions and separately agreed services are excluded.</p>
<p>Published by ERPintegrators.com, by <span itemprop="publisher" itemscope="" itemtype="https://schema.org/Organization"><span itemprop="name">Solvync Inc.</span></span>. Check every slip against your records before filing.</p>
</section>
'''
heading_end = html.index("</h1>") + len("</h1>")
html = html[:heading_end] + "\n" + facts + html[heading_end:]
page.write_text('<div itemscope="" itemtype="https://schema.org/SoftwareApplication">\n' + html + "\n</div>\n")
PYSCHEMA
# Numeric entities preserve accented text when the store parses an HTML fragment.
python3 - <<'PYHTML'
from pathlib import Path
page = Path("static/description/index.html")
page.write_bytes(page.read_text().encode("ascii", "xmlcharrefreplace"))
PYHTML
echo "README.rst and static/description/index.html written"
