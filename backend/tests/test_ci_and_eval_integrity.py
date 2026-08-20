"""Guards on the things that report on everything else.

A broken CI file and an eval that measures the wrong path both fail silently:
the repository looks green while nothing is being checked. These tests make
both loud.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_is_valid_yaml():
    """The workflow was invalid YAML for six sprints and nobody noticed.

    `DATABASE_URL: sqlite+pysqlite:///:memory:` ends a plain scalar with a
    colon, which YAML rejects. GitHub would have refused the whole file, so
    every "CI passes" claim rested on the steps having been run by hand.
    """
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert document["jobs"], "workflow parsed but declares no jobs"


def test_ci_declares_both_a_baseline_and_a_model_gate():
    yaml = pytest.importorskip("yaml")
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert "eval" in jobs, "the free baseline gate must run on every push"
    assert "eval-model" in jobs, "the model path must have its own gate"
    assert "eval-integrity" in jobs, "overlap and out-of-vocabulary must be reported"

    model_job = json.dumps(jobs["eval-model"])
    # The safety floor applies to the model path too, not only the baseline.
    assert "--fail-under-redflag 1.0" in model_job


def test_model_path_refuses_to_run_without_a_key(monkeypatch):
    """Without a key the engine degrades to rules, which is the trap.

    The first version of this tool printed a full results table in that state,
    which reads as a model evaluation and measured nothing. It must exit.
    """
    from app.ai.eval.run import ProviderUnavailable, _provider

    monkeypatch.setattr("app.core.config.get_settings", lambda: _no_key_settings())
    with pytest.raises(ProviderUnavailable) as excinfo:
        _provider("openai")
    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "Refusing to run rather than degrade" in message


def _no_key_settings():
    from app.core.config import Settings

    return Settings(
        environment="test", openai_api_key=None, anthropic_api_key=None, local_llm_base_url=None
    )


def test_baseline_provider_is_labelled_as_not_a_model():
    from app.ai.eval.run import CODE_PATHS

    assert "no model called" in CODE_PATHS["baseline"]
    for provider in ("openai", "anthropic", "local"):
        assert "eight-stage engine" in CODE_PATHS[provider]


def test_every_vignette_set_declares_synthetic_provenance():
    from app.ai.eval.runner import VIGNETTE_SETS

    for name, path in VIGNETTE_SETS.items():
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        note = payload.get("provenance_note", "")
        assert "SYNTHETIC" in note.upper(), f"{name} does not state its provenance"


def test_out_of_vocabulary_set_is_actually_out_of_vocabulary():
    """The OOV set is only meaningful if it really avoids the map.

    Guards against the failure where someone 'fixes' the low OOV score by
    adding its phrases to the terminology map, which would delete the
    measurement instead of improving the system.
    """
    from knowledge.terminology import get_terminology

    from app.ai.eval.overlap import measure_set
    from app.ai.eval.runner import OOV_VIGNETTES_PATH, VIGNETTES_PATH, load_vignettes

    mapping = get_terminology()
    main, _ = measure_set(mapping, "main", load_vignettes(VIGNETTES_PATH))
    oov, _ = measure_set(mapping, "oov", load_vignettes(OOV_VIGNETTES_PATH))

    # The main set is near-total vocabulary overlap by construction; the OOV
    # set must stay well below it or it has stopped being a control.
    assert main.mean_surface_word_coverage > 0.4
    assert oov.mean_surface_word_coverage < main.mean_surface_word_coverage / 2


def test_adversarial_set_covers_every_red_flag_rule_from_both_sides():
    from app.ai.eval.runner import ADVERSARIAL_VIGNETTES_PATH, load_vignettes
    from app.ai.red_flags import RULES, CaseFacts

    vignettes = load_vignettes(ADVERSARIAL_VIGNETTES_PATH)
    danger = {v.target_rule for v in vignettes if v.adversarial_kind == "danger_paraphrased"}
    decoy = {v.target_rule for v in vignettes if v.adversarial_kind == "trigger_words_no_danger"}

    # Every code the rule table can emit needs a probe in both directions.
    emitted: set[str] = set()
    probes = [
        CaseFacts(concepts={"crushing_chest_pain"}),
        CaseFacts(concepts=set(), spo2=85),
        CaseFacts(concepts=set(), respiratory_rate=34),
        CaseFacts(concepts={"choking"}),
        CaseFacts(concepts={"fever"}, systolic_bp=88, respiratory_rate=26),
        CaseFacts(concepts={"stroke"}),
        CaseFacts(concepts={"neck_stiffness", "fever"}),
        CaseFacts(concepts={"seizure"}, age_band="adult"),
        CaseFacts(concepts={"lethargy"}, age_band="under5"),
        CaseFacts(concepts={"diarrhea", "dehydration"}, age_band="under5"),
        CaseFacts(concepts={"pregnancy_bleeding"}),
        CaseFacts(concepts=set(), pregnant=True, systolic_bp=160),
        CaseFacts(concepts={"melena"}),
        CaseFacts(concepts={"hemoptysis"}),
        CaseFacts(concepts={"cough", "night_sweats"}, duration_days=40),
        CaseFacts(concepts=set(), glucose_mmol=25),
        CaseFacts(concepts=set(), glucose_mmol=2.0),
        CaseFacts(concepts={"thunderclap_headache"}, systolic_bp=195),
        CaseFacts(concepts={"anemia", "dyspnea_at_rest"}),
    ]
    for facts in probes:
        for check in RULES:
            flag = check(facts)
            if flag is not None:
                emitted.add(flag.code)

    missing_danger = sorted(emitted - danger)
    missing_decoy = sorted(emitted - decoy)
    assert not missing_danger, f"no paraphrased-danger case for: {missing_danger}"
    assert not missing_decoy, f"no decoy case for: {missing_decoy}"
