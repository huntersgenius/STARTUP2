# The strategic verdict

Workstreams 7 and 9.

---

## 1. Would a feldsher in a rural clinic use it?

**I could not run the app on a device.** No emulator or display was available in
the audit environment, so `flutter run` and a stopwatch were not possible. What
follows is from the code and from the 53 passing widget tests; the timing
question is named as an experiment in `audit/06-next-90-days.md`, not answered
here.

**What the UI gets right, verifiably.** Touch targets are 64 dp against a
Material minimum of 48, body text is 18 pt, and a widget test asserts *every*
decision button meets the target — someone thought about a tablet held in a cold
room by a person wearing gloves. Red-flag banners render above everything else
in red, asserted by test. The disclaimer is always present with a suggestion,
asserted by test. Uzbek is the default and falls back to Uzbek for an unknown
language, and a test asserts no clinical string is left in English. A full
consultation completes with no network, asserted end to end.

**Time per consultation — the unmeasured question that decides adoption.** The
form has one free-text field, 8 vital fields and 60 symptom chips. A doctor
seeing 40 patients in a shift has roughly 6-8 minutes each, of which the AI step
must take well under one. Nobody has measured it. My estimate from the form
alone is that a trained user gets through it in 45-90 seconds if they use chips
and skip most vitals — which is plausible, and is exactly the kind of estimate
that should not be believed without a stopwatch. **The value proposition dies
quietly at whatever threshold turns out to be real, and no one has looked.**

**Trust.** The evidence chain is visible: every differential must cite a
retrieved protocol chunk or it is dropped (`engine.py:388-395`), so a clinician
can see the basis. Uncertainty is legible without a statistics background —
after the remediation the UI shows *kuchli / o'rtacha / zaif moslik* rather than
a percentage, with a line saying it is not a probability. Low confidence
produces follow-up questions instead of a ranked guess. Rejection requires a
written reason, which makes the decision feel like the clinician's judgement
rather than a rubber stamp — and produces the only training signal the company
will get.

**Language.** The Uzbek in the code is real Uzbek, not transliterated Russian —
the red-flag messages read as a clinician would write them
("Sil kasalligiga shubha… Davolashni o'zingiz boshlamang"). Both scripts are
handled by the matcher. But the audit set found the two arms failing in
opposite directions: identical Russian sentences return no concepts where Uzbek
returns several, and Uzbek over-fires on negation where Russian does not. The
reported "+0.0 pp language gap" is an artefact of translating 26 templates in
parallel, not evidence of parity.

**Failure states.** Offline is genuinely designed for, not bolted on: local
Drift store, on-device rule engine, an explicit sync indicator with a pending
count, and a `duplicate` path so a replayed batch is not double-applied. The
gaps are the ones the brief predicts: a tablet shared by three staff has no
fast user-switch in the code I read, and a sync backlog growing for a week
shows a count but nothing escalates it.

---

## 2. What did this execution actually prove?

Claims now backed by working, independently reproducible code:

- **A complete, coherent system exists and builds.** 438 backend tests, 53
  Flutter tests, `flutter analyze` clean, `tsc --noEmit` clean, `next build`
  succeeds. I reproduced all of it from a clean clone.
- **The deterministic safety layer survives every failure mode of the model.**
  Provider outage, invalid schema, empty response, malformed JSON and an open
  circuit breaker all still fire red flags, still force referral, and still mark
  the answer degraded — and the degradation is shown to the clinician.
- **The clinician gate has no hole.** Every path that persists or exports a
  suggestion requires a role-authorised decision, including the offline sync
  path that used to bypass it.
- **Offline-first works end to end** and is the most convincing part of the
  build.
- **The project can measure itself honestly and act on it.** The remediation
  pass found its own headline number was measuring a dictionary, published the
  gap, found a red-flag rule that contradicted its own cited WHO source, fixed
  it, and discovered its CI had never run. That capability is rarer than any
  feature here.

## 3. What does it only appear to have proven?

- **"97.6% accuracy."** Agreement between text this project wrote and a
  dictionary this project wrote, across 26 templates, scored against its own
  answer key. The repository says so; a deck will not.
- **"100% red-flag recall."** Recall on rule-shaped text. On text written
  without reference to the map, 32.7% — and **0 of 10** where the danger is
  described only in words.
- **"Never emits controlled substances."** The block cannot fire; five of five
  tested opioids and benzodiazepines reach the clinician (AUD-002).
- **"$0.05 per consultation, 6-second p95."** Never measured against a model.
- **"Zero direct competitors."** The state is building CDS into DMED (AUD-009).
- **"Regulatory Sandbox as an advantage."** A route to apply for, not a status
  held.

## 4. Is the moat argument sound?

**Not as stated.** The plan says the moat is Uzbek-language clinical data. Two
problems.

First, the volume. A rough order: fine-tuning or even robust retrieval over
Uzbek clinical speech needs somewhere in the tens of thousands of labelled
consultations before it beats a good rules-plus-LLM pipeline — call it
20,000-50,000 with clinician decisions attached. At the plan's own Year-1 target
of 40 clinics and a plausible 20 AI-assisted consultations per clinic per week,
that is roughly 40,000 per year — so the moat becomes real somewhere in **year
two**, and only if the rejection reasons are captured well enough to be labels.
The architecture does capture them (`ClinicianDecision.action`, `final_text`,
`reason`), which is the single most valuable design decision in the repository.

Second, and worse: **the state has a bigger version of the same moat**, already.
DMED holds the national record. A Cabinet-approved roadmap puts an AI medical
assistant and CDS tools inside it by end-2026. A well-funded entrant does not
need to out-collect SihhatAI; the incumbent system already has the data and the
mandated distribution.

The defensible moat is narrower and more boring: **the offline rural clinic**.
DMED integration presumes connectivity. A product that works on a mini-PC in a
QVP with intermittent power, in Uzbek, with a formulary that matches what is
actually on the shelf, is not something a central IT programme builds well.
That is a real moat and it is the part this repository has actually built.

## 5. Is a CDS the right first product?

**Probably not first — but it is close, and the team has already de-risked more
of it than a pivot would preserve.**

The strongest lower-risk wedge into the same customer is **structured
consultation capture and formulary-aware prescribing support, with a
deterministic vital-signs alarm layer and no diagnostic ranking at all.** Same
tablet, same clinic, same offline architecture, same sales conversation. It
almost certainly falls outside the medical-device classification that a
diagnostic CDS attracts, it needs no clinical accuracy claim, and it collects
exactly the dataset that makes the CDS possible later. The formulary work, the
offline sync, the audit chain, the i18n and the UI all carry over unchanged.

Does it beat the current plan? **On risk-adjusted terms for the next 12 months,
yes.** On terms of what gets funded, no — "AI diagnoses patients" raises money
and "structured intake" does not. The honest resolution is to sell the wedge and
build the CDS behind the sandbox application, which is roughly what
`docs/PILOT_RUNBOOK.md` §0 already forces.

## 6. If you had to kill this project, what is the argument?

Made as strongly as I can:

> The safety layer does not read the patient's words. Every danger sign is a
> keyword lookup in a dictionary the team wrote, and on sentences the team did
> not write it catches none of the dangers that are described in words rather
> than numbers. Twelve months of work has produced a system whose headline
> safety number is 100% and whose real one is closer to zero on the cases that
> matter most — a rural patient describing crushing chest pain in ordinary
> Uzbek. Meanwhile the state has announced it is building the same product into
> the national medical record system with mandated distribution and the entire
> country's data, and a foreign-hosted diagnostic CDS faces a 6-12 month device
> registration that is not in the plan. The moat is a dataset the incumbent
> already owns. Return the money.

**Does it hold? No — but only just, and only because of one thing.**

The argument's factual core is correct and this audit confirmed all of it. What
it gets wrong is the direction of travel. A team that discovers its own headline
number is circular, publishes the number that replaces it, finds a rule
contradicting its own cited source, and writes "CI has never run" in its own
README is a team that will find the next problem too. That is the asset here —
not the code, and certainly not the 97.6%.

The kill argument becomes correct if, three months from now, the model-path
evaluation still has not been run for want of an API key, or the text-only
red-flag recall is still zero, or a clinician still has not reviewed a single
vignette. Those are three cheap, dated tests. Set them, and let them decide.
