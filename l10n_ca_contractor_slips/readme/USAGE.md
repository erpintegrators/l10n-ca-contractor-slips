1. Go to **Accounting > Reporting > Contractor Slips (T4A, T5018)** (**Invoicing** on Odoo
   Community) and create a return on the main company: choose the slip type and the year. A T4A
   return covers the calendar year. For T5018 on a fiscal year, the year is the one in which the
   period ends. The return shows its due date and notes a period that has not ended yet, or a gap
   since the last T5018 period.
2. Click **Calculate slips**. Each slip shows the amount calculated from payments, the payments
   behind it, and any warning: a missing SIN or business number, an incomplete address, a name split
   from the contact, characters CRA will not keep, a payment not matched to a posted bill, or a
   payment that settles a journal entry. The return also names vendors paid on tagged accounts whose
   contact is not set to this slip, and contractors whose slip for the period was cancelled in an
   amendment; the notes are kept in the return's messages when you finalize.
   Contacts with an address outside Canada are left out and listed on the return; confirm each one
   is a non-resident before filing.
3. Correct the contacts and source records and click **Recalculate**, or enter an adjustment with
   its reason. Adjustments survive recalculation. The recipient details on a slip come from the
   contact, so correct them there. Payments made outside Odoo belong in Odoo too, for example as a
   bank entry to a tagged account: the $500 test uses the calculated amount, so an adjustment cannot
   create a slip for someone below it.
4. Click **Finalize**. The module refuses to finalize if bills, payments or contacts changed since
   the last calculation, checks the settings and every slip, builds the XML file and validates it
   against CRA's schemas. Download the file and upload it through CRA's Internet File Transfer, then
   click **Mark as filed** and record the confirmation number.
5. Deliver the slips by the due date:
   - **Email slips** queues an email for each recipient who consented, sent within a few minutes by
     a scheduled job, and never sends the same slip twice. Each slip shows whether its email is
     queued, sent or failed, with the reason for a failure, and the return's messages name each
     recipient whose email failed so you can print their slip or email it again.
     Sent means your outgoing mail server accepted the email. A message that bounces after that
     shows only in the sender's mailbox, so give a paper copy to anyone who says the email did not
     arrive.
   - Recipients with a portal login they have used find their slips under *Tax slips* on their
     portal home page.
   - **Print slips** prints two copies of each slip on one sheet for everyone else, including
     recipients who asked for paper, whose email address is not valid, or whose portal login was
     revoked or never used; the summary after emailing names them. **Print duplicates** prints replacement copies marked DUPLICATE. Giving T5018 slips
     to subcontractors is optional.
6. To correct a filed return, open the latest filed version and click **Amend**. Change the slips
   that are wrong and explain the change in the amendment note, naming each recipient (up to 1,309
   characters), then finalize. Only changed slips go in the file; a change of address alone does not
   amend a slip. To cancel slips, tick **Cancel this slip** in a separate amendment, because CRA takes
   amended and cancelled slips in separate submissions. Recipients of a cancelled slip get a copy
   marked cancelled by email, on the portal and in print. Contractors missed on the original go in
   a new original return for the same year, which picks up only the contractors the filed return
   does not have.
7. Keep a record of when and how you asked each individual for their SIN, of each recipient's email
   consent, and of how each slip reached its recipient.
