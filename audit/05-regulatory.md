# Regulatory and operational reality

Workstream 8. Where I could not establish a fact from a citable source, it is
marked **unverified** rather than guessed. I did not guess about medicine or
about Uzbek law.

---

## 1. What legal status does this system need before a real patient?

### 1.1 Medical device / software classification

Uzbekistan registers medical devices through the Ministry of Health, on a
risk-based classification following the EU model (Class I, IIa, IIb, III).
Registration involves technical and clinical evaluation and expert council
review, takes **6-12 months**, and the registration is valid for **5 years**.

**Whether clinical decision support software falls inside that regime, and at
what class, is unverified.** None of the sources I could reach states how
software-as-a-medical-device is classified in Uzbekistan. In the EU model this
product would be caught — software intended to provide information used to take
decisions for diagnostic purposes is a device, and CDS that drives diagnosis or
therapy tends to land at IIa or higher. Whether Uzbekistan's adoption of the
classification carries that reading across is exactly the question to put to a
regulatory consultant, in writing, before a pilot.

This matters more than the sandbox question, because a 6-12 month registration
path is a fundraising fact: it sits between the pilot and any government
contract, and it is not in the plan's timeline.

### 1.2 The IT Park regulatory sandbox

`docs/EXECUTIVE_SUMMARY.md` treats the sandbox as an existing advantage
("Regulatory Sandbox (2025)", "**Why Now**"). What I could establish:

- EY and IT Park Uzbekistan signed an agreement to create a regulatory sandbox,
  described as a special legal regime within the International Digital
  Technology Centre "Enterprise Uzbekistan".
- A proposed AI sandbox framework for Uzbekistan names **healthcare** among its
  high-potential areas.
- Uzbekistan has a Strategy for the Development of AI Technologies to 2030 and
  approved an AI bill in 2025.

What I could **not** establish, and therefore mark unverified: that a health-AI
sandbox cohort is open, what its admission criteria are, what relief from device
registration (if any) admission grants, or that anyone has been admitted.

`docs/PILOT_RUNBOOK.md` §0 already treats sandbox application as a hard blocker
before any installation. That is the right posture and it is stricter than the
executive summary's tone. The two documents should agree.

### 1.3 Personal data

The governing law is **"On Personal Data" No. ZRU-547, 2 July 2019**. Article
27-1, added in 2021, required personal data of Uzbek citizens to be stored on
servers inside the country.

**This changed during the project's lifetime.** Amendments in force
**27 March 2026** replaced blanket localisation with a conditional regime:

- Still **mandatory to store inside Uzbekistan**: biometric data (including
  facial images, iris, **voice samples**), genetic data (including results of
  medical and genetic testing), and telecommunications subscriber data.
- Everything else may be processed abroad only where three conditions hold
  **simultaneously**: established information-security requirements are met,
  international personal-data protection standards are complied with, and there
  is oversight by an authorised state body of Uzbekistan.

Three consequences for this repository:

1. **AUD-001 is a legal exposure, not only a security one.** Posting a patient's
   name, phone number and symptom narrative to `api.openai.com` is cross-border
   processing of personal data by a startup that satisfies none of the three
   conditions.
2. **The plan's "AWS ap-south-1 (Mumbai)" hosting line is a decision that has
   to be defended**, not a default. It is legal under the amended regime only
   with the three conditions in place. Hosting in Uzbekistan removes the
   argument entirely and is the cheaper answer at pilot scale.
3. **The absent Whisper feature is a hard constraint, not a soft one.** Voice
   samples are biometric data and must stay in the country. If voice input is
   built, it has to run on the edge box or on Uzbek infrastructure. This is a
   good reason to keep it descoped, and a good reason to delete the unused
   `record` dependency so nobody assumes the path is half-built.

**Can the repository supply the evidence an application would need?** Partly,
and better than most at this stage: a hash-chained audit log with a CSV export
built for the purpose, a de-identification module with a measured red-team
suite, an evaluation harness with published integrity analysis, and a written
safety review. Two gaps: the export is not independently verifiable (AUD-007),
and every clinical number in it describes synthetic vignettes, which a reviewer
will ask about in the first meeting.

---

## 2. The pilot runbook, followed literally as the founder on day one

`docs/PILOT_RUNBOOK.md` §0 lists four blockers and says "Do not install anything
at a clinic until all four are true":

| Blocker | Status |
|---|---|
| Licensed clinical advisor engaged, has reviewed the vignette set | not done |
| IT Park sandbox application filed | not done |
| Clinic agreement signed | not done |
| Patient consent process agreed | not done |

**So the runbook cannot be started today, and that is the runbook working
correctly.** It is not a documentation defect; it is a business gate that the
document is honest about. The instruction "stop and escalate rather than working
around it" is the right instruction and it should not be softened.

Steps 1-3 (create clinic, create staff, generate keys) are executable from the
repository as it stands. The key-generation step correctly warns that losing
`PII_ENCRYPTION_KEY` makes a clinic's records permanently unreadable — which
raises the question the brief asks and the runbook does not answer:

- **Key rotation:** there is no rotation path. `Patient.set_pii` encrypts with
  the single configured key; changing it orphans every existing row. Before a
  second clinic, the ciphertext needs a key-id prefix so two keys can coexist.
- **Restore from backup:** `infra/ops/backup.sh` verifies the dump. A restore
  test that also proves the *decryption* key still works — a full round trip
  from backup to a readable patient name — is not in the repository and is the
  only test that makes the backup real.

---

## 3. Observability: can anyone tell that quality has degraded in the field?

There is no ground truth in a clinic, so the answer must be a proxy. The right
proxy is the clinician rejection and edit rate: if doctors start rejecting more
suggestions, something changed.

**It is instrumented but not alerted.** `metrics.inc("sihhatai_decisions_total",
{"action": …})` is recorded on every decision (`ai.py:222`), and
`/admin/metrics` reports per-clinic counts including `undecided`. So the signal
exists and a human can look at it.

Missing:

- a **rejection-rate** metric rather than raw counts, per clinic and per week;
- any alert threshold at all — nothing fires when it moves;
- a **degraded-share** alert, which is the leading indicator: a clinic whose
  answers silently become rules-only because the breaker is open looks fine on
  a rejection-rate chart and is getting a much weaker product;
- **red-flag firing rate per 100 consultations**, which is the one number that
  would reveal AUD-003 in production — a clinic seeing far fewer alarms than
  its case mix implies is a clinic where the terminology map is not matching.

That last one is the cheapest safety instrument available and it should exist
before the first pilot.

---

## 4. The edge bundle

`infra/edge/` exists. I could not verify a clinic install end to end from this
container — the Docker build cannot reach pypi through this sandbox's TLS
interception, and a control build fails identically, so the failure is mine and
not the repository's. Unverified, and it should be verified on real hardware
before a clinic visit, because the runbook's definition of done is "onboarded
end to end by following this document alone, with no engineer present".

The specific questions to answer on that hardware: what a non-engineer sees when
the mini-PC is powered off mid-sync, and what happens when the edge model's
protocol version lags the cloud's — the prompt version is part of the cache
bucket, so a stale edge box will not poison the cache, but nothing tells an
operator that the box is behind.

---

## Sources

- [Uzbekistan Medical Device Classification System & Registration — OMC Medical](https://omcmedical.com/uzbekistan-medical-device-classification-system-registration/)
- [Guide to Uzbekistan Medical Device Registration — Operon Strategist](https://operonstrategist.com/uzbekistan-medical-device-registration/)
- [EY and IT Park to set up regulatory sandbox in Uzbekistan — Tashkent Times](https://tashkenttimes.uz/national/13293-ey-and-it-park-to-set-up-regulatory-sandbox-in-uzbekistan)
- [AI sandboxes supporting Uzbekistan's private sector — The Datasphere Initiative](https://www.thedatasphere.org/news/ai-sandboxes-supporting-uzbekistans-private-sector/)
- [Uzbekistan to integrate AI into healthcare, courts, and public services — Kun.uz, 22 July 2025](https://kun.uz/en/news/2025/07/22/uzbekistan-to-integrate-ai-into-healthcare-courts-and-public-services)
- [Personal data compliance in Uzbekistan — Legal500](https://www.legal500.com/developments/thought-leadership/personal-data-compliance-in-uzbekistan/)
- [Localization of personal data in Uzbekistan: transition to a more flexible regulatory model — Settle Advisory](https://settleadvisory.com/news-en/localization-of-personal-data-in-uzbekistan-transition-to-a-more-flexible-regulatory-model/)
- [Uzbekistan dismantles strict data localization regime — Dentons](https://www.dentons.com/en/insights/articles/2026/march/31/uzbekistan-dismantles-strict-data-localization-regime) (returned HTTP 403 to this audit; cited for the reader, not relied on)
