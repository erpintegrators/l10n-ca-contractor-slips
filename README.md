# T4A and T5018 Slips

**ERPintegrators.com** | by **Solvync Inc.**

T4A box 048 and T5018 slips for Odoo 18 Community and Enterprise, calculated from the vendor
payments you actually made, with the CRA XML file validated against CRA's published schemas,
customized PDF slips, email and portal delivery, and amended returns.

| Module | Summary |
| --- | --- |
| [l10n_ca_contractor_slips](l10n_ca_contractor_slips/) | T4A box 048 and T5018 slips from vendor payments |

## Before you file

This module helps you prepare T4A and T5018 returns for the Canada Revenue Agency (CRA). It gives
no tax, accounting or legal advice; decide what is reportable with your accountant.

You remain responsible for every slip, the file you upload, deadlines, delivery to recipients, and
any CRA penalty or interest. Check each slip against your records before filing.

Schema validation checks the file's format only. It cannot tell you whether amounts or identifiers
are correct, or whether CRA will accept the return.

Solvync Inc. has no affiliation with CRA, and CRA has not endorsed this module.

This software is licensed under the GNU Lesser General Public License, version 3. To the extent
the law allows, it is provided as is, without warranty of any kind, including as to accuracy, and
Solvync Inc. is not liable for any loss arising from its use.

## Privacy

The business using this module is accountable for the personal information in it under PIPEDA or its
provincial equivalent. Solvync receives none of it. The only outside call the module makes downloads
CRA's public schemas from canada.ca, and it sends no data.

SINs are collected under section 237 of the Income Tax Act and used for these slips only. Odoo stores
them in the database and its backups without encryption, so give accounting administrators two-step
login and mask SINs in any copy made for support. Each SIN sits on the contact, kept for the main
company that collected it, on every slip that reported it and in the CRA file stored with each
return. Clearing it from the contact leaves those
copies, and the module cannot yet remove SINs from final or filed returns, so agree with your
accountant how you will destroy them once each return's six-year record period ends.
CRA requires the recipient's consent before slips are emailed, and emailed slips carry the full SIN
over ordinary email. Odoo deletes the emailed copy once it is sent; a failed email keeps its PDF
until the slip is emailed again, for at most 30 days. Odoo 18 controls dynamic template editing
through system administration and **Mail Template Editor** permissions. Give those rights only
to people trusted to see SINs; Odoo 18 has no separate Restrict Template Rendering setting. An exposed SIN will usually meet the real risk of significant harm test, which brings
duties to report and notify (PIPEDA section 10.1; Alberta PIPA section 34.1).

## Third-party material

Printed slips carry the National Flag of Canada, drawn from public-domain geometry
(`static/src/img/fip_flag.svg`), beside CRA's name, and CRA's own box wording. CRA requires both on
slips you print yourself. Neither is Solvync's work, the LGPL licence covers Solvync's own code and
text only, and their presence on a slip says nothing about CRA approval of this module.

## Publisher and project links

Published through [ERPintegrators.com](https://erpintegrators.com), a Solvync Inc. brand.
The module is developed and maintained by [Solvync](https://solvync.com).
For setup questions or a defect report, email [info@erpintegrators.com](mailto:info@erpintegrators.com).
Include your Odoo version and the steps to reproduce the issue. Remove SINs and other personal
data from screenshots and logs before sharing them.

## Development

The tests need CRA's schema package, which `dev/fetch_schemas.sh` downloads:

```bash
dev/fetch_schemas.sh
odoo -d slips_test -i l10n_ca_contractor_slips --test-enable \
  --test-tags /l10n_ca_contractor_slips --stop-after-init
```

Run this from any Odoo 18 server whose addons path includes this repository. With
`L10N_CA_SLIPS_REQUIRE_SCHEMAS=1` set, a missing schema package fails the run; the GitHub workflow
sets it. `dev/seed_demo.py` loads a demo company with
contractors, bills and payments through `odoo shell`.

From the first public release on, a change to a record loaded with `noupdate` (the slip email
template, the sequences, the tags, the portal entry) or to a stored field's type ships with a
version bump and a migration script under `migrations/`, so databases that already have the
module pick it up.

## License

LGPL-3.0. See [LICENSE](LICENSE). Maintained by [Solvync](https://solvync.com).
