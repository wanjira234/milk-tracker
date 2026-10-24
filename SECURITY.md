# Security notes

What is protected, how, and what is not done yet. The application-level items under "In place" are covered by tests in `tests/`; the platform settings (Supabase row-level security, hosting, secrets stores) are configuration and are checked by hand, not by tests.

## In place

**Accounts and roles**
- Three roles (farmer, vet, admin). A farmer sees only their own farm; a vet only the farms on the routes they are allocated; an admin everything. Every page calls `require_login(roles=...)` and the data itself is filtered in `src/accounts.py`, so hiding a menu link is never the only protection.
- Admin is never self-service. Farmers and vets can sign up but cannot log in until an admin approves them, and a farm record is created only at approval. Pending sign-ups are capped.
- A page opened directly without logging in shows only the sign-in box and never reaches the database.

**Passwords and login codes**
- Passwords are hashed with scrypt (N=2^14, r=8, p=1, random salt per password) from the standard library. The settings are stored with each hash so they can be raised later. Minimum 8 characters; trivial digit strings are refused.
- The shared owner password has one lockout for everyone: five wrong tries from any browser lock the owner login for 15 minutes. Prefer individual admin logins and set the owner password to a long random value.
- Five wrong passwords lock the account for 15 minutes, and the lock is stored in the database, so reloading the page does not reset it. A browser session also stops after five wrong tries.
- Unknown emails take the same time as wrong passwords (a dummy hash is checked), and the error never says whether an email exists. The one exception is a correct password on a sign-up that is still waiting for approval.
- SMS login codes are 6 digits, single-use, valid for 10 minutes, limited to 5 tries, one per minute and five per hour. They are stored as an HMAC-SHA256 with a per-code salt, never in clear.
- Temporary passwords set by an admin must be changed at first login.

**Data**
- All SQL values are passed as parameters. The few dynamic parts of a query (column names in an update) come from fixed whitelists, never from user input.
- Composite foreign keys make the database refuse a record that points at another farm's cow, semen or calf.
- A vet can act only on service requests, alerts and vaccination days for their own routes; a farmer can cancel only their own requests. These checks are on the server side and tested, including with another vet's and another farm's ids.
- On Supabase the schema is run with "Run and enable RLS", so the public API keys cannot read the tables. The app connects server-side through the connection pooler.

**Secrets**
- Keys and passwords live only in `.env` (git-ignored) or the host's secrets store, never in the code or the repo. The app stays locked if no owner password or admin phone is configured.
- The demo seed takes its password from the environment or generates one, shows the target database host and asks for confirmation before writing, and runs in one transaction so an interrupted run leaves nothing half-written. Use a separate demo database.

**SMS and AI**
- Alerts are texted only after a preview and a confirmation, once per alert (claimed in the database first, so a double click cannot text everyone twice), and only to the farms the alert is for. Texts that would not fit in two segments or use characters outside the basic SMS alphabet are refused. Every message, sent or failed, is logged.
- The AI only rewords advice. The numbers and the feed name come from the model, and any rewording that changes them, promises a result, adds a link or breaks the length limit is rejected and a plain template is sent instead.
- Page content is never built from user input as HTML: the only `unsafe_allow_html` use is fixed styling.

See [docs/SSDLC.md](docs/SSDLC.md) for the risk assessment, threat model and testing by development stage.

## Not done yet

- No email or phone verification at sign-up (the admin's approval is the check).
- No password-reset flow or two-factor login.
- No audit log of who changed what.
- The app relies on Streamlit Community Cloud for HTTPS and on Supabase for database backups; neither is configured or tested by us.
- Phone numbers and farm records are personal data. A data-protection review (Kenya's Data Protection Act, consent and retention) has not been done and should happen before real farmers are onboarded at scale.
- The Africa's Talking account is a sandbox: SMS reaches the simulator, not real phones, until a live account is set up.

## Reporting a problem

Open an issue on this repository, or contact the team through the hackathon submission.
