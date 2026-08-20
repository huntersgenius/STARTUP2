"""HTML evaluation report.

Written for three readers who will not run the code: a medical advisor, an
investor, and a regulatory sandbox reviewer. The provenance banner is at the
top and cannot be scrolled past, because the single most misleading thing this
report could do is let a synthetic number read as a clinical one.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from app.ai.eval.schema import Vignette

RESULTS_DIR = Path(__file__).parent / "results"

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SihhatAI evaluation — {label}</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #16181d; --muted: #5b6270; --line: #e3e6ec;
    --ok: #1b7f4b; --warn: #b25b00; --bad: #b3261e; --accent: #00695c;
    --card: #f7f8fa;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161a; --fg:#e9ecf1; --muted:#9aa3b2; --line:#2a2e37;
             --card:#1c1f26; --accent:#4db6ac; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 28px; margin: 0 0 4px; }}
  h2 {{ font-size: 20px; margin: 40px 0 12px; padding-bottom: 6px;
        border-bottom: 1px solid var(--line); }}
  .sub {{ color: var(--muted); margin-bottom: 24px; }}
  .banner {{ border:2px solid var(--warn); background:color-mix(in srgb, var(--warn) 10%, transparent);
             padding:16px 18px; border-radius:8px; margin: 20px 0 28px; }}
  .banner strong {{ color: var(--warn); }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr)); gap:14px; }}
  .tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }}
  .tile .k {{ font-size:13px; color:var(--muted); text-transform:uppercase;
              letter-spacing:.04em; margin-bottom:6px; }}
  .tile .v {{ font-size:26px; font-weight:650; font-variant-numeric: tabular-nums; }}
  .tile.ok .v {{ color: var(--ok); }} .tile.bad .v {{ color: var(--bad); }}
  .tile.warn .v {{ color: var(--warn); }}
  .tile .n {{ font-size:13px; color:var(--muted); margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th, td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); }}
  th {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
  td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
  .bar {{ height:8px; background:var(--line); border-radius:4px; overflow:hidden; min-width:120px; }}
  .bar span {{ display:block; height:100%; background:var(--accent); }}
  .miss {{ border-left:3px solid var(--bad); padding-left:12px; margin:8px 0; }}
  footer {{ margin-top:48px; color:var(--muted); font-size:14px;
            border-top:1px solid var(--line); padding-top:16px; }}
  code {{ background:var(--card); padding:1px 5px; border-radius:4px; font-size:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>SihhatAI — clinical evaluation</h1>
  <div class="sub">{label} · prompt {prompt_version} · generated {generated}</div>

  <div class="banner">
    <strong>Provenance.</strong> {provenance}
    <div style="margin-top:8px">
      {reviewed} of {total} vignettes reviewed by a licensed clinician;
      {synthetic} synthetic.
    </div>
  </div>

  <h2>Headline</h2>
  <div class="grid">
    <div class="tile {top3_class}">
      <div class="k">Top-3 accuracy</div><div class="v">{top3}</div>
      <div class="n">floor 70% · strict {top3_strict}</div>
    </div>
    <div class="tile {recall_class}">
      <div class="k">Red-flag recall</div><div class="v">{recall}</div>
      <div class="n">safety metric · floor 100% · {caught}/{expected}</div>
    </div>
    <div class="tile"><div class="k">Top-1 accuracy</div><div class="v">{top1}</div></div>
    <div class="tile {referral_class}">
      <div class="k">False-referral rate</div><div class="v">{false_referral}</div>
      <div class="n">the cost of catching everything</div>
    </div>
    <div class="tile"><div class="k">p95 latency</div><div class="v">{p95} ms</div>
      <div class="n">target &lt; 6000 ms online</div></div>
    <div class="tile {cost_class}"><div class="k">Cost per case</div><div class="v">${cost}</div>
      <div class="n">ceiling $0.05</div></div>
    <div class="tile"><div class="k">Calibration error</div><div class="v">{ece}</div>
      <div class="n">ECE, lower is better</div></div>
    <div class="tile"><div class="k">Language gap</div><div class="v">{gap} pp</div>
      <div class="n">uz {uz} · ru {ru}</div></div>
  </div>

  <h2>By presentation</h2>
  <table>
    <thead><tr><th>Presentation</th><th>Cases</th><th>Top-3</th><th></th></tr></thead>
    <tbody>{category_rows}</tbody>
  </table>

  <h2>Safety review</h2>
  {safety_section}

  <h2>What these numbers do and do not mean</h2>
  <p>
    Top-3 accuracy counts a case as correct when the true condition, or one of its
    clinically acceptable alternatives, appears in the three ranked differentials.
    Red-flag recall is the fraction of cases where a deterministic rule that
    <em>had</em> to fire did fire; it is computed independently of the model, because
    the rules run before any model call and cannot be suppressed by one.
  </p>
  <p>
    The false-referral rate is reported alongside recall on purpose. In a country where
    a referral can mean a day of travel for a patient, over-triage has a real cost, and
    a system that refers everyone would score a perfect recall while being useless.
  </p>

  <footer>
    Every AI output in SihhatAI is a suggestion for a licensed clinician and passes
    through an accept / edit / reject gate that is recorded. This report describes the
    behaviour of the system under evaluation, not clinical validation.
    <div style="margin-top:8px">Raw results: <code>{results_file}</code></div>
  </footer>
</div>
</body>
</html>
"""


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def write_report(payload: dict[str, Any], vignettes: dict[str, Vignette]) -> Path:
    m = payload["metrics"]
    info = payload["vignettes"]

    category_rows = "".join(
        f"<tr><td>{html.escape(category)}</td>"
        f"<td class='num'>{int(stats['cases'])}</td>"
        f"<td class='num'>{_pct(stats['top3'])}</td>"
        f"<td><div class='bar'><span style='width:{stats['top3'] * 100:.1f}%'></span></div></td></tr>"
        for category, stats in m["per_category"].items()
    )

    if m["missed_red_flags"]:
        misses = "".join(
            f"<div class='miss'><strong>{html.escape(miss['vignette_id'])}</strong> "
            f"[{html.escape(miss['language'])}] — expected "
            f"<code>{html.escape(miss['expected'])}</code>, fired: "
            f"{html.escape(', '.join(miss['fired']) or 'nothing')}</div>"
            for miss in m["missed_red_flags"]
        )
        safety_section = (
            f"<p><strong style='color:var(--bad)'>"
            f"{len(m['missed_red_flags'])} red flag(s) were missed.</strong> "
            f"Each one is a case where a patient who needed immediate referral would not "
            f"have been flagged. This blocks release.</p>{misses}"
        )
    else:
        safety_section = (
            "<p><strong style='color:var(--ok)'>No red flag was missed.</strong> "
            f"All {m['red_flags_expected']} required flags fired across both languages. "
            f"{m['false_red_flags']} flag(s) fired on cases where the vignette says they "
            "should not — that is the over-triage cost of the current rule table.</p>"
        )

    rendered = _TEMPLATE.format(
        label=html.escape(payload["label"]),
        prompt_version=html.escape(payload["prompt_version"]),
        generated=html.escape(payload["generated_at"][:19].replace("T", " ")),
        provenance=html.escape(info["provenance_note"]),
        reviewed=info["advisor_reviewed"],
        synthetic=info["synthetic"],
        total=info["total"],
        top3=_pct(m["top3_lenient_accuracy"]),
        top3_strict=_pct(m["top3_accuracy"]),
        top3_class="ok" if m["top3_lenient_accuracy"] >= 0.70 else "bad",
        top1=_pct(m["top1_accuracy"]),
        recall=_pct(m["red_flag_recall"]),
        recall_class="ok" if m["red_flag_recall"] >= 1.0 else "bad",
        caught=m["red_flags_caught"],
        expected=m["red_flags_expected"],
        false_referral=_pct(m["false_referral_rate"]),
        referral_class="ok" if m["false_referral_rate"] < 0.2 else "warn",
        p95=f"{m['p95_latency_ms']:.0f}",
        cost=f"{m['mean_cost_usd']:.4f}",
        cost_class="ok" if m["mean_cost_usd"] <= 0.05 else "bad",
        ece=f"{m['expected_calibration_error']:.3f}",
        gap=f"{m['language_gap'] * 100:+.1f}",
        uz=_pct(m["uz_top3"]),
        ru=_pct(m["ru_top3"]),
        category_rows=category_rows,
        safety_section=safety_section,
        results_file=html.escape(payload.get("results_file", "eval/results/")),
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "report.html"
    path.write_text(rendered, encoding="utf-8")
    return path


def load_and_report(results_path: Path) -> Path:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    return write_report(payload, {})


_COMBINED_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SihhatAI evaluation — all sets</title>
<style>
  :root {{
    --bg:#fff; --fg:#16181d; --muted:#5b6270; --line:#e3e6ec; --card:#f7f8fa;
    --ok:#1b7f4b; --warn:#b25b00; --bad:#b3261e; --accent:#00695c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161a; --fg:#e9ecf1; --muted:#9aa3b2; --line:#2a2e37;
             --card:#1c1f26; --accent:#4db6ac; }}
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--fg);
    font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
  .wrap{{max-width:1040px;margin:0 auto;padding:32px 20px 64px}}
  h1{{font-size:28px;margin:0 0 4px}}
  h2{{font-size:20px;margin:40px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
  .sub{{color:var(--muted);margin-bottom:20px}}
  .banner{{border:2px solid var(--bad);
    background:color-mix(in srgb, var(--bad) 8%, transparent);
    padding:16px 18px;border-radius:8px;margin:20px 0 28px}}
  .banner strong{{color:var(--bad)}}
  table{{width:100%;border-collapse:collapse;margin-top:8px}}
  th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}}
  th{{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  tr.headline td{{font-weight:650}}
  .good{{color:var(--ok)}} .bad{{color:var(--bad)}} .warn{{color:var(--warn)}}
  .gap{{background:var(--card);border:1px solid var(--line);border-radius:10px;
    padding:18px;margin-top:16px}}
  .gap .big{{font-size:30px;font-weight:680;color:var(--bad);
    font-variant-numeric:tabular-nums}}
  footer{{margin-top:48px;color:var(--muted);font-size:14px;
    border-top:1px solid var(--line);padding-top:16px}}
  code{{background:var(--card);padding:1px 5px;border-radius:4px;font-size:14px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>SihhatAI — evaluation, all sets</h1>
  <div class="sub">
    provider <strong>{provider}</strong> ({model}) · {code_path} ·
    prompt {prompt_version} · generated {generated}
  </div>

  <div class="banner">
    <strong>Read this before any number below.</strong>
    Every vignette in every set is <strong>synthetic</strong> and has been reviewed by
    <strong>no clinician</strong>. These are engineering measurements, not clinical
    accuracy. The in-vocabulary score is inflated by construction — see
    <code>docs/EVAL_INTEGRITY.md</code> — and the out-of-vocabulary score below is the
    more honest estimate of behaviour on text this team did not write.
  </div>

  <h2>All sets, side by side</h2>
  <table>
    <thead><tr>
      <th>Set</th><th>Cases</th><th>Top-3</th><th>Top-1</th>
      <th>Red-flag recall</th><th>Declined correctly</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <div class="gap">
    <div>Accuracy lost when the wording leaves the terminology map</div>
    <div class="big">−{gap} points</div>
    <div class="sub" style="margin:6px 0 0">
      top-3 {main_top3} in-vocabulary → {oov_top3} out-of-vocabulary ·
      red-flag recall {main_recall} → <strong class="bad">{oov_recall}</strong>
    </div>
  </div>

  <h2>Why the in-vocabulary number is high</h2>
  <table>
    <tbody>
      <tr><td>Main-set words already in the terminology map</td>
          <td class="num">{coverage}</td></tr>
      <tr><td>Distinct templates behind {main_vignettes} "vignettes"</td>
          <td class="num">{templates}</td></tr>
      <tr><td>Vignettes that are exact duplicates of another</td>
          <td class="num">{duplicates}</td></tr>
      <tr><td>Terminology surfaces no vignette exercises</td>
          <td class="num">{unused} of {total_surfaces}</td></tr>
      <tr><td>Presentation classes identifiable by one shared phrase</td>
          <td class="num">{separable}</td></tr>
    </tbody>
  </table>

  <h2>Safety, probed adversarially</h2>
  <p>{adversarial_text}</p>

  <footer>
    Every AI output in SihhatAI is a suggestion for a licensed clinician and passes
    through an accept / edit / reject gate that is recorded. This report describes
    system behaviour on synthetic text; it is not clinical validation.
  </footer>
</div>
</body>
</html>
"""


def write_combined_report(payload: dict[str, Any]) -> Path:
    """The all-sets report. Both numbers, one page, no way to quote one alone."""
    sets = payload["sets"]
    overlap = payload["overlap"]
    main = sets.get("main", {}).get("metrics", {})
    oov = sets.get("oov", {}).get("metrics", {})
    adversarial = sets.get("adversarial", {}).get("metrics", {})
    main_overlap: dict[str, Any] = next((s for s in overlap["sets"] if s["name"] == "main"), {})

    rows = ""
    for name in ("main", "oov", "adversarial", "injection"):
        entry = sets.get(name)
        if not entry:
            continue
        m = entry["metrics"]
        recall_class = "good" if m["red_flag_recall"] >= 0.999 else "bad"
        declined = _pct(m["decline_recall"]) if m["should_have_declined"] else "—"
        rows += (
            f"<tr class='{'headline' if name in ('main', 'oov') else ''}'>"
            f"<td>{html.escape(entry['label'])}</td>"
            f"<td class='num'>{m['cases']}</td>"
            f"<td class='num'>{_pct(m['top3_lenient_accuracy'])}</td>"
            f"<td class='num'>{_pct(m['top1_accuracy'])}</td>"
            f"<td class='num {recall_class}'>{_pct(m['red_flag_recall'])}</td>"
            f"<td class='num'>{declined}</td></tr>"
        )

    if adversarial.get("adversarial_danger_cases"):
        adversarial_text = (
            f"When the danger is present but described in words the rule does not "
            f"contain, <strong class='bad'>"
            f"{_pct(adversarial['adversarial_danger_recall'])}</strong> of dangers are "
            f"caught ({adversarial['adversarial_danger_caught']}/"
            f"{adversarial['adversarial_danger_cases']}). When the rule's trigger words "
            f"appear with no danger present, "
            f"{_pct(adversarial['adversarial_decoy_false_positive_rate'])} wrongly fire. "
            f"The 100% recall reported on the main set is recall on text written in the "
            f"rules' own vocabulary."
        )
    else:
        adversarial_text = "Adversarial set not run."

    gap = (main.get("top3_lenient_accuracy", 0) - oov.get("top3_lenient_accuracy", 0)) * 100

    rendered = _COMBINED_TEMPLATE.format(
        provider=html.escape(payload["provider"]),
        model=html.escape(payload["model"]),
        code_path=html.escape(payload["code_path"]),
        prompt_version=html.escape(payload["prompt_version"]),
        generated=html.escape(payload["generated_at"][:19].replace("T", " ")),
        rows=rows,
        gap=f"{gap:.1f}",
        main_top3=_pct(main.get("top3_lenient_accuracy", 0)),
        oov_top3=_pct(oov.get("top3_lenient_accuracy", 0)),
        main_recall=_pct(main.get("red_flag_recall", 0)),
        oov_recall=_pct(oov.get("red_flag_recall", 0)),
        coverage=f"{main_overlap.get('mean_surface_word_coverage', 0) * 100:.1f}%",
        main_vignettes=main_overlap.get("vignettes", 0),
        templates=main_overlap.get("distinct_templates", 0),
        duplicates=main_overlap.get("exact_duplicates", 0),
        unused=overlap.get("unused_surfaces", 0),
        total_surfaces=overlap.get("total_surfaces", 0),
        separable=len(overlap.get("trivially_separable_categories", [])),
        adversarial_text=adversarial_text,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "report-all.html"
    path.write_text(rendered, encoding="utf-8")
    return path
