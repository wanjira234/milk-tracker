# Secure system development cycle (SSDLC)

Maziwa Plus (Milk Tracker), FNB App of the Year Hackathon 2026. This describes what the team did at each stage, what evidence is in the repository, and what is not done. For the control-by-control list see [SECURITY.md](../SECURITY.md).

## 1. Security requirements (risk assessment)

**What we protect**

| Asset | Why it matters |
|---|---|
| Farmers' phone numbers and names | Personal data; a leak enables spam and fraud |
| Farm records: milk, feed, herd, breeding | Commercially sensitive to the farmer; shows income and costs |
| Vet visit and semen records, with prices | Costs are deducted from milk payments, so wrong data costs money |
| Logins, password hashes, SMS codes | A stolen login exposes a whole farm, or every farm for an admin |
| The SMS channel | Misuse could spam farmers or spread a false outbreak alert |
| API keys (Africa's Talking, Claude, database) | A leak means cost and data exposure |

**Who could attack, and how (team assessment, high / medium / low)**

| Risk | Likelihood | Impact | Requirement we set |
|---|---|---|---|
| One farm reads another farm's data | Medium | High | Role checks on every page and in the data layer; the database refuses cross-farm references |
| Password or code guessing | High | High | Hashed passwords, lockouts, throttled codes, one shared lockout for the owner password |
| Self-service sign-up used to gain admin or vet powers | Medium | High | Admin is never self-service; sign-ups wait for admin approval |
| SQL injection | Medium | High | Parameterised SQL only |
| SMS misuse, spam or a mistaken alert | Medium | Medium | Preview and confirm; one send per alert; limits per farmer per day; every send logged |
| AI rewording changes the advice | Medium | Medium | The AI only rewords; any changed number or promise is rejected |
| Secrets committed or leaked | Medium | High | Secrets only in `.env` or the host's secrets store |
| Personal data kept after someone leaves | Medium | Medium | A farmer, vet or admin can delete their account; an admin can delete a login, farm or route |
| Data-protection law (Kenya Data Protection Act) | Medium | High | Flagged as an open item; a review is needed before real farmers are onboarded at scale |

## 2. Threat modelling and design review

We modelled the system as three kinds of users and four trust boundaries: the browser to the Streamlit app, the app to the Supabase Postgres database, the app to the SMS provider, and the scheduled jobs to the AI service. Threats were walked through per boundary (spoofing, tampering, information disclosure, denial of service, elevation of privilege).

Design decisions that came from this:

- **Least privilege by role.** Farmer: own farm. Vet: farms on allocated routes. Admin: all. Farm pages are closed to admins and vets, so each role sees only its own work.
- **Defence in depth.** The menu hides pages, each page checks the role again, the data layer filters by role, and the database enforces ownership with composite foreign keys.
- **No self-service privilege.** Admin accounts are created by an admin; sign-ups wait for approval.
- **The AI has no authority.** The model computes the advice; the AI can only rephrase it, and a checker rejects any change.
- **Confirmation before anything is sent to many people.** Alerts are previewed, confirmed and sent once.

Findings from the design review that we fixed: the shared owner password was only rate-limited per browser session, so it now has one lockout shared by all sessions (5 wrong tries, 15 minutes). The vet and the admin each saw farm pages that belong to the farmer, and these were closed.

## 3. Development (secure coding practices)

- Passwords hashed with scrypt, salted, with the settings stored beside each hash. Constant-time comparison for secrets. A dummy hash is checked for unknown emails so timing does not reveal who has an account.
- SMS login codes are stored only as salted HMAC-SHA256 values; single-use, short-lived, limited tries.
- All SQL values are parameters; the few dynamic parts come from fixed whitelists.
- No user input is rendered as HTML; the only `unsafe_allow_html` use is fixed styling.
- Secrets are read from the environment; `.env` is git-ignored; the app stays locked if no owner password or admin phone is configured.
- Every change goes through a pull request on a branch, with the full test suite run before it is opened.
- Destructive actions (deleting accounts, farms, routes) need the word DELETE typed, and the only admin cannot be deleted.

## 4. Security testing

- **Automated tests:** more than 440, run against a real Postgres. They include access to another farm's or another vet's records, wrong roles opening pages, lockouts, code throttling, SMS and AI rewording checks, and deletion rules.
- **Static analysis:** bandit run over the code: no high-severity findings. The seven medium findings are all SQL strings assembled from fixed column whitelists, each checked by hand. The low findings are non-secret flags and the random generator used only to make simulated demo data.
- **Manual checks:** row-level security on the Supabase tables is checked by hand in the dashboard; the demo uses a separate database holding simulated data.
- **Not done:** an external penetration test, dependency vulnerability scanning in CI, and load testing.

## 5. Assessment and secure integration

- **Hosting:** Streamlit Community Cloud (HTTPS) and Supabase (managed Postgres, backups). We rely on their controls and have not tested them.
- **Database access:** the app connects server-side through the connection pooler; the public API keys cannot read the tables because row-level security is on.
- **SMS:** Africa's Talking sandbox for the demo; messages reach the simulator, not real phones. A live account must be set up, and sender registration completed, before real farmers are texted.
- **AI:** Claude Haiku receives the advice facts, not personal details such as names or phone numbers (the message text is generated from the farm's numbers and feed names).
- **Before real use:** a data-protection review (consent, retention, a privacy notice), password reset, an audit log of who changed what, two-factor login for admins, and dependency scanning in the build.

## Known gaps, honestly

No email or phone verification at sign-up (admin approval is the check), no password reset, no two-factor login, no audit log, no penetration test, no data-protection review yet, and SMS is sandbox-only.
