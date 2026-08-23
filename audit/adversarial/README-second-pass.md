# Second-pass adversarial set — reproduction

Files added by the second audit pass. They sit alongside the first pass's
`vignettes_audit_oov.json` / `run_audit_set.py` / `test_audit_probes.py` rather
than replacing them: two corpora written blind by two auditors is the evidence,
and merging them would destroy it.

| File | What it is |
|---|---|
| `vignettes_audit2_oov.json` | 48 vignettes written before reading `knowledge/terminology.csv` |
| `redflag_evasion.json` | 19 cases — one per rule, danger present, rule's words absent |
| `redflag_decoy.json` | 12 cases — trigger words present, danger absent |
| `run_audit2_eval.py` | scores all of the above plus the repository's own sets |
| `probe2.py` | text → concepts → firing rules, for attributing a failure to a word |

Every number in `audit/08-addendum-second-pass.md` comes from these.

## Run everything

```bash
cd /path/to/repo
PYTHONPATH=backend:. .venv/bin/python audit/adversarial/run_audit2_eval.py -v
```

Expected tail:

```
  set              recall      n
  oov               32.3%     62
  evasion           10.5%     38
  decoy               n/a      0
  repo-main        100.0%    158
  repo-oov           4.5%     22
```

`repo-main 100.0%` and `repo-oov 4.5%` are the check that licenses the rest:
the harness reproduces `make eval` and `REMEDIATION.md` exactly, using the
production code path (`TerminologyMap.clinical_concepts` +
`DiagnosticEngine._vital_concepts` + `red_flags.evaluate`).

**If you change `age_band` in `run_audit2_eval.py`, re-check those two numbers
first.** The paediatric rules test `facts.age_band in ("infant", "under5")`;
an off-by-one band name silently drops 24 expectations and the harness reports
84.8% instead of 100.0%. That happened on the first attempt.

## Attribute a single failure to a word

```bash
PYTHONPATH=backend:. .venv/bin/python audit/adversarial/probe2.py \
  "ko'kragim og'riyapti" "ko'kragim qattiq og'riyapti"
```

```
text     : ko'kragim og'riyapti
concepts : ['chest_pain']
red flags: []

text     : ko'kragim qattiq og'riyapti
concepts : []
red flags: []
```

## The failing tests

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_audit_p0_red_flag_evasion.py -v
```

12 failures, all deliberate. They assert the behaviour a clinician is entitled
to assume. Make them pass by teaching the concept layer to read the clinical
picture — **not** by adding these sentences to `terminology.csv`.

## Decomposing `158/158` (finding A2-003)

```bash
python3 - <<'PY'
import collections, json
vs = json.load(open('backend/app/ai/eval/data/vignettes.json'))['vignettes']
exp = [(v['text_uz'], f) for v in vs for f in v.get('must_not_miss', [])]
by = collections.defaultdict(set)
for t, f in exp:
    by[f].add(t)
print('expectations counted in the headline:', 2 * len(exp))
print('distinct (text, flag) pairs         :', len(set(exp)))
print('rules tested by exactly one text    :', sum(1 for f in by if len(by[f]) == 1), 'of', len(by))
ALL = {'acs_suspected','airway_compromise','gi_bleeding','hemoptysis',
       'hyperglycemic_emergency','hypertensive_emergency','hypoglycemia','hypoxia',
       'imci_danger_sign','meningism','pediatric_dehydration','preeclampsia_suspected',
       'pregnancy_bleeding','respiratory_distress','seizure','sepsis_suspected',
       'severe_anemia','stroke_fast','tb_suspected'}
print('never exercised                     :', sorted(ALL - set(by)))
PY
```

```
expectations counted in the headline: 158
distinct (text, flag) pairs         : 32
rules tested by exactly one text    : 10 of 15
never exercised                     : ['airway_compromise', 'preeclampsia_suspected',
                                       'respiratory_distress', 'seizure']
```

## Reproducing the `сильно` → `tuberculosis` collision (finding A2-002)

```bash
PYTHONPATH=backend:. .venv/bin/python -c "
import sys; sys.path[:0]=['backend','.']
from knowledge.terminology import get_terminology
m = get_terminology()
for t in ['Сил нет','сильная боль','сильный кашель','сильно болит голова']:
    print(f'{t:22s} -> {[x.term.concept for x in m.extract(t)]}')
"
```

Every line reports `tuberculosis`. The surface is `sil` (Uzbek for
tuberculosis); the Cyrillic→Latin pass at `knowledge/terminology.py:261` turns
`сильно` into `silno`, and `MAX_SUFFIX_CHARS = 5` lets `sil` claim it.

## Reproducing the seed failure (finding A2-001)

```bash
cd backend
ENVIRONMENT=dev DATABASE_URL="sqlite+pysqlite:////tmp/seedtest.db" \
  SECRET_KEY=x PII_ENCRYPTION_KEY="ZGV2LW9ubHktaW5zZWN1cmUtcGlpLWtleS0zMmJ5dGU=" \
  PYTHONPATH=.. ../.venv/bin/python -m alembic upgrade head
ENVIRONMENT=dev DATABASE_URL="sqlite+pysqlite:////tmp/seedtest.db" \
  SECRET_KEY=x PII_ENCRYPTION_KEY="ZGV2LW9ubHktaW5zZWN1cmUtcGlpLWtleS0zMmJ5dGU=" \
  PYTHONPATH=.. ../.venv/bin/python -m app.seed --if-empty; echo "exit=$?"
```

```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError)
  NOT NULL constraint failed: patients.pii_blob
exit=1
```

Same failure against PostgreSQL 16. `infra/docker-compose.yml:48-50` chains
`alembic upgrade head && python -m app.seed --if-empty && uvicorn ...`, so
uvicorn never starts.
