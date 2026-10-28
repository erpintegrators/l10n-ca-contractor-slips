- Quebec RL-1 slips (box O, code RD) are not produced. Revenu Québec requires software
  certification for RL-1 XML.
- No T4A box 022. If you withheld income tax from a contractor, which is rare, CRA needs a slip for
  them whatever the amount: set their bills to **Not reported** so this return leaves them out, and
  file their slip separately, for example with CRA's Web Forms.
- Each amended submission totals and counts only the slips in it, as CRA's corrections page
  describes. Confirm with your accountant before filing your first amendment.
- To correct a SIN or business number already filed, cancel the slip in an amendment and file it
  again in a new original return. CRA's pages do not say how an amended slip with a different
  identifier is matched to the original; the module warns when an amended slip carries a new one.
- The federal identity signature on printed slips is drawn from the public-domain flag beside the
  agency's name. CRA's own artwork is the exact reference.
- A contact counts as a non-resident when its address is outside Canada. CRA asks for T5018 slips
  for resident subcontractors wherever the work was done, so a resident with a foreign address must
  have its address corrected. A dedicated non-resident flag is planned.
- Fees paid to non-residents for services in Canada belong on the T4A-NR, which this module does
  not produce.
- Slips show the full SIN to accounting administrators and to the recipient signed in to the
  portal. Anyone opening a shared link, and read-only accountants, see the last three digits.
  The CRA file and the emailed PDFs are restricted to accounting administrators.
- A credit note applied to a bill counts on the day the two are matched, in the time zone set on
  the company's contact (UTC when none is set). Matching a credit note in a later year moves its
  effect into that year, so match credit notes before filing.
- With Odoo Enterprise, a payment recorded without a journal entry that covers both bills and
  credit notes is split across them by amount, which can be off when their mixes differ. Check
  those slips' payment lists before filing.
- No tool yet removes SINs from final or filed returns once the six-year record period ends.
  Clearing a SIN from the contact leaves the copies on slips and in the stored CRA files.
- The $500 test looks at box 048 alone. CRA adds up all T4A boxes, so a recipient who gets other
  T4A amounts from you elsewhere may need a box 048 slip below $500. Do not tag commission accounts:
  commissions go in box 020.
- With early payment discounts set to *Never* on the company, the discount is spread across the
  bill's tax as well, so box 048 can be a few cents above the fees paid. The Canadian default, *On
  early payment*, is exact.
- A T5018 period that ends on the last day of a month is due on the last day of the sixth month
  after it, following CRA's rule for corporation returns.
- Returns always belong to the main company and file under its RP or RZ account. A branch that
  files under a program account of its own cannot have its own return yet.
