# SihhatAI — pilot runbook

Everything needed to take one clinic from "interested" to "using it daily".
Follow it in order. If a step cannot be completed, stop and escalate rather
than working around it — every step here exists because skipping it caused a
problem somewhere.

**Definition of done for this runbook:** a clinic is onboarded end to end by
following this document alone, with no engineer present.

---

## 0. Before you go — the blockers

Do not install anything at a clinic until all four are true. These are legal
and clinical prerequisites, not paperwork.

| Blocker | Evidence needed | Owner |
|---|---|---|
| Licensed clinical advisor engaged | Signed advisory agreement; they have reviewed the vignette set | Founders |
| IT Park Regulatory Sandbox application filed | Acknowledgement letter | Founders |
| Clinic agreement signed | Signed LOI or contract naming the responsible physician | Sales |
| Patient consent process agreed with the clinic | The consent text the clinic will use, in Uzbek and Russian | Clinical advisor |

> **Until sandbox admission, the pilot runs on consented patients only, and no
> AI suggestion may be the sole basis for a clinical decision.** That is not a
> formality — it is the condition under which this system is lawful to use.

---

## 1. Prepare (office, day −7)

1. **Create the clinic.**
   Admin dashboard → Clinics → New clinic. Record name, region, type, tier
   (1 = feldsher point, 2 = rural QVP/SVP, 3 = district polyclinic), and whether
   it will run an edge server.

2. **Create the staff accounts.**
   Admin → Bulk users. One row per person, with their real role — a nurse
   cannot close the clinical gate, and giving everyone `doctor` to avoid a
   support call defeats the audit trail.

3. **Generate the clinic's keys.**
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"     # SECRET_KEY
   python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"  # PII_ENCRYPTION_KEY
   ```
   Put both in the ops password manager **before** the box ships. Losing
   `PII_ENCRYPTION_KEY` makes that clinic's records permanently unreadable.

4. **Prepare the edge box** (only if the clinic has poor connectivity).
   Flash the image, write the `.env`, label the box with its clinic name and
   support number. Boot it once in the office and confirm `/health` returns
   `ok` — never let a first boot happen in a clinic.

5. **Prepare the tablets.**
   Install the app, set the server address, log in once as each user to confirm
   the accounts work, then log out. Charge them fully.

6. **Print the materials.**
   - The one-page staff guide (section 8), in Uzbek, one copy per clinician.
   - The patient consent text, 100 copies.
   - A card with the support phone number, taped to each tablet.

---

## 2. Install (clinic, day 0, ~2 hours)

1. Introduce yourself to the head physician. Confirm the responsible physician
   named in the agreement is present.
2. Install the edge box following `infra/edge/INSTALL.md`. Skip if cloud-only.
3. Connect each tablet and run one **test consultation on a fake patient**
   named "Test Bemor". Confirm end to end:
   - a suggestion appears,
   - the red-flag banner appears when you enter chest pain with breathlessness,
   - accept/edit/reject records and the consultation closes.
4. **Delete the test patient** before leaving.
5. Walk to the far corner of the clinic and confirm the tablet still works
   there. If Wi-Fi does not reach the consulting rooms, that is a finding —
   record it, and expect a higher offline share from this clinic.

---

## 3. Train the staff (clinic, day 0, 45 minutes)

Train everyone who will touch the system, together, in the clinic, on the
tablets they will use. Not a slide deck.

Cover exactly this, in this order:

1. **What it is and is not.** "It suggests, you decide. It is never a diagnosis.
   Nothing happens to a patient because of this app — it happens because you
   decided." Say it in these words; it is the sentence that keeps them safe and
   keeps us lawful.
2. **One full consultation**, done by a clinician, not by you.
3. **The red banner.** What it means, and that it appears without the internet.
4. **Accept / edit / reject.** Stress that *reject* is a normal, expected
   answer, and that the reason they type is how the system improves. A pilot
   with a 100% acceptance rate is a pilot where nobody is really reading.
5. **The sync indicator.** How many records are waiting, and that an unsent
   record is not a lost record.
6. **What to do when it is wrong.** Reject, write why, carry on. Call support
   only if the app itself is broken.

End by having each person complete one consultation unaided. Do not leave
until everyone has.

---

## 4. First week

**Daily, from the office:**
- Admin → Dashboard. Check: consultations recorded, undecided count, degraded
  share, sync conflicts.
- **Undecided > 0 for more than a day** means suggestions are being generated
  and not acted on. Call the clinic — usually it means a workflow problem, not
  a bug.
- Call the clinic once on day 1, day 3 and day 7. Ask one question: "what
  annoyed you today?"

**Escalate immediately if:**
- a clinician reports a suggestion that would have harmed a patient,
- a red flag failed to appear for a case that clearly needed one,
- any patient identifier appears somewhere it should not.

The first two go to the clinical advisor the same day. The third is a data
incident: preserve the evidence, notify the founders, do not "fix and move on".

---

## 5. Weekly metrics review (30 minutes, every Monday)

Look at these five numbers per clinic, and write one sentence about each:

| Metric | Where | What a bad value means |
|---|---|---|
| AI acceptance rate | Dashboard | Very high (>90%) suggests rubber-stamping; very low (<30%) suggests the suggestions are not useful |
| Undecided suggestions | Dashboard | The clinician gate is being bypassed or ignored |
| Red flags fired | Dashboard | Zero over a week in a busy clinic is suspicious, not reassuring |
| Degraded share | Dashboard | Connectivity or provider problems; clinicians are getting rules-only answers |
| Sync conflicts | Dashboard | Two people editing the same record; check the merge log |

Then read **five rejected suggestions in full**, including the clinician's
reason. This is the highest-value half hour of the week: it is the only place
where the system's real failure modes show up in a clinician's own words.

Feed what you learn into the vignette set. A rejection that reveals a genuine
gap should become a new eval case that week.

---

## 6. Rollback

**Rollback is always available and is never a failure.** Any clinician may stop
using the system at any time with no explanation.

| Situation | Action | Time |
|---|---|---|
| One clinician unhappy | Deactivate their account; they revert to paper | Minutes |
| Clinic wants to pause | Admin → deactivate clinic users; leave the box installed | Minutes |
| Suspected clinical safety problem | Stop the clinic, notify the advisor, preserve the audit log, do not delete anything | Immediately |
| Bad release | Redeploy the previous image tag; migrations are backwards-compatible within a minor version | ~15 minutes |
| Data incident | Preserve, notify founders, export the audit log, do not modify records | Immediately |

Patient records are never deleted as part of a rollback. The clinic keeps its
data and can export it.

**Restoring a database:**
```
infra/ops/restore.sh /backups/sihhat-<stamp>.dump "$DATABASE_URL"
```
Then verify the audit chain via Admin → Audit → Verify. It must report `ok`.
A restore that breaks the chain is a reportable event, not a routine one.

---

## 7. Exit criteria for the pilot

The pilot succeeds when, across five clinics over eight weeks:

- ≥ 200 consultations recorded with a clinician decision on each,
- acceptance rate between 40% and 85% (engaged, not rubber-stamping),
- zero missed red flags reported by clinicians,
- zero patient-identifier incidents,
- ≥ 3 of 5 clinics say they would keep using it if asked to pay,
- the audit log exports cleanly and verifies for the sandbox reviewer.

If acceptance sits above 90%, treat it as a **negative** result until proven
otherwise and go and watch someone use it.

---

## 8. One-page staff guide (print this, in Uzbek)

> ### SihhatAI — qanday ishlatiladi
>
> **1. Kiring.** Pochta va parolingizni kiriting.
>
> **2. Bemorni toping yoki qo'shing.** Ro'yxatdan qidiring; yangi bemor uchun
> pastdagi «Yangi bemor» tugmasini bosing.
>
> **3. Shikoyatni yozing.** Bemor nima desa, o'sha so'zlar bilan yozing.
> Mikrofon tugmasi bilan gapirib ham bo'ladi.
>
> **4. Belgilarni belgilang va ko'rsatkichlarni kiriting.** Harorat, puls,
> bosim — o'lchaganlaringizni. O'lchamaganingizni bo'sh qoldiring.
>
> **5. «Tahlil qilish» tugmasini bosing.**
>
> **6. Qizil ramka chiqsa — bu shoshilinch.** Bemorni zudlik bilan
> yo'naltiring. Internet bo'lmasa ham bu ramka ishlaydi.
>
> **7. Qaror qabul qiling.** Har bir taklif uchun:
> **Qabul qilish** — rozisiz.
> **Tahrirlash** — deyarli to'g'ri, o'zingiz to'g'rilaysiz.
> **Rad etish** — noto'g'ri. Sababini yozing — bu tizimni yaxshilaydi.
>
> **Rad etish — normal holat.** Qaror har doim sizniki.
>
> **8. Internet yo'q bo'lsa ham ishlayvering.** Yozuvlar planshetda saqlanadi
> va internet paydo bo'lganda o'zi yuboriladi. Yuqoridagi ko'rsatkich nechta
> yozuv kutayotganini ko'rsatadi.
>
> **Yordam kerak bo'lsa:** +998 XX XXX XX XX (ish vaqtida)

---

## 9. Contacts

| Role | Who | When to call |
|---|---|---|
| Clinic support | +998 XX XXX XX XX | App broken, cannot log in, box offline |
| Clinical advisor | (name) | Any suggestion that could have harmed a patient |
| Founders | (name) | Data incident, regulator contact, press |
