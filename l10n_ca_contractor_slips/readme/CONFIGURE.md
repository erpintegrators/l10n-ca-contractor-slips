Work in the main company for all of the steps below. Returns belong to the main company, cover
every branch, and read their settings, each contact's slip type and each contact's email consent
from there. In a database with several businesses, each main company files its own returns, with
its own program accounts, slip types and email consent. Odoo shows the settings to administrators
only.

On Odoo 19, the module also installs the standard **VAT Number Validation** module for Canadian
business-number checks. Preparing and merging contractor contacts needs Odoo's **Contact Creation**
permission as well as the accounting administrator role. Grant these through the normal user settings.

1. In **Accounting > Configuration > Settings** (**Invoicing** on Odoo Community), under
   *Canadian Contractor Slips*, enter:
   - the payer's **RP** program account (T4A) and **RZ** program account (T5018), for example
     123456789RP0001;
   - how you sign in to CRA's Internet File Transfer: **My Business Account**, a **web access
     code**, or **Represent a Client**. With My Business Account, enter your 9-digit business number
     or a 15-character program account as the **transmitter** account. With a web access code, the
     file carries the 15-character account you sign in with (the return's RP or RZ account unless
     you enter another). A representative enters their **RepID** and, if they like, the firm's name
     as **transmitter name**; the RepID goes in the file only with Represent a Client;
   - the **filing contact**, a person with a 10-digit phone number and an email address of at most
     60 characters;
   - the **T5018 reporting period**: calendar year or fiscal year. Once you file for a period, CRA
     expects the same period every year unless it authorizes a change in writing;
   - whether to report the **whole mixed bill** on T5018 (the default) or the services lines only,
     and which **T5018 threshold** to apply (see the setting's help).

   File T5018 only if more than half of your business income comes from construction. Other payers
   report construction subcontractors in T4A box 048. Slip amounts must be in Canadian dollars, so
   the company's currency must be CAD.
2. On each contractor's contact, in the *Invoicing* tab, set **Canadian slip** to T4A or T5018 and
   choose the **slip recipient type**: individual or sole proprietor, corporation, or partnership.
   A return will not finalize until it is set on every contractor.
   Enter the SIN for individuals while working in the main company. Each main company keeps the SIN
   it collected, visible to its own accounting administrators only. The surname and given
   name come from the contact name; type them on the contact when the name has more than two words
   or is written surname first. The return lists each slip's surname and given name, so check them
   before finalizing.
   Businesses use the standard **Tax ID** field for their 15-character business number. Tick
   **Slips by email** only when the recipient has agreed, in writing or electronically, to receive
   slips by email, and keep that consent with your records. Consent covers only the company it was
   given to, so a recipient paid by two of your businesses consents to each separately. Tick
   **Wants paper slips** for anyone who asked for paper.
   The other recipient details (name, address, recipient type) belong to the contact, so every
   company that can open the contact sees them. Where businesses in one database should not see
   each other's contractors, set the contact's **Company** field to the main company that pays
   them. Avoid setting it to a branch: head-office users without that branch could not open the
   contact.
   Merging a contractor's contact with another moves its SIN, consent, slip type and slips, filed
   ones included, to the kept contact, whose portal login can then open them. So only an accounting
   administrator who works in every main company that pays the contractor can merge it. Duplicate
   rules set to merge automatically in Odoo Enterprise's Data Cleaning run as the system and skip
   that check, so leave contractors to manual merging.
   Each vendor bill records the contact's slip type when it is posted, in the **Canadian slip**
   field under *Other Info*. A contractor who moves from T4A to T5018 mid-year keeps the
   earlier bills on T4A. Bills posted before you flagged a contact follow the contact. An accounting
   administrator can set a bill to **Not reported** to leave it out.
3. Tag the expense accounts you pay contractors from with **T4A box 048: fees for services** or
   **T5018: construction services**. Bill lines on those accounts count for contacts set to the
   slip, and the return names any other vendor paid on them. For T4A, lines with a service
   product count too. Lines with a goods product never count. If you hold back part of each
   subcontractor bill, tag the holdback account with the T5018 tag as well, so holdbacks count when
   they are paid. Payments booked from bank, cash and credit card journals straight to a tagged
   account count as well. T4A payers who hold back part of a contractor's fees tag the holdback
   account with the T4A tag. Release a holdback with a vendor bill on the holdback account, or pay it
   straight from that account; a payment that settles a journal entry is flagged and left out,
   because the entry does not say what it paid for. The same goes for opening balances: in your
   first year on Odoo, enter unpaid contractor bills as vendor bills on a tagged account so their
   payments count.

   Odoo copies the tags of the account whose code sorts just before a new account's code. After you
   tag an account, check the tags on any account you create next to it, and review which accounts
   carry each tag before every filing season.

   CRA asks for box 048 on payments between businesses, including corporations, in every industry.
   It currently assesses penalties for leaving box 048 out only where its administrative policy for
   trucking applies: from 2025, businesses in the trucking industry paying Canadian-controlled
   private corporations in that industry. That policy concerns completing box 048; penalties for
   filing an information return late are a separate matter. Flag service contractors unless your
   accountant advises otherwise.
4. The CRA schemas download automatically the first time you finalize a return. To fetch them
   ahead of time, use **Download CRA schemas** in the same settings block. A server without internet
   access can point the system parameter `l10n_ca_contractor_slips.cra_schema_url` at a copy of
   CRA's schema package on an internal web server.

   The default is CRA's **2026 submission package** until 10 January 2027, then the
   **2027 package from 11 January 2027**, using Eastern time. The filing service date determines
   the package, independently of the tax year on the return. The draft return displays the
   default package year. CRA's electronic filing service closes on 22 December 2026 and reopens
   on 11 January 2027; the module displays a notice during that period. Preparation is possible
   during the closure, but wait for the service to reopen before uploading. A custom schema
   mirror overrides the automatic package selection; its administrator must maintain it.
   Existing final and filed XML files are preserved. Check CRA's
   [current XML specifications](https://www.canada.ca/en/revenue-agency/services/e-services/filing-information-returns-electronically-t4-t5-other-types-returns-overview/xml-specs.html)
   before submitting.
5. Print slips at actual size, with any "fit to page" or scaling option in the print dialog turned
   off: CRA's rules for slips you print yourself set their size and text size.

Stored CRA XML and queued slip PDFs are private to the paying company's accounting administrators.
Public attachment flags and download tokens do not grant access to these files. Upgrading the
module revokes legacy public links and restores payer restrictions while retaining the file bytes.
Recipients use their own slip portal, which applies the recipient and masking rules.
