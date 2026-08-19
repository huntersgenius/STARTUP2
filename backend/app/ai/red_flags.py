"""Deterministic red-flag rules.

These fire **before and independently of** any model call. Nothing in this
module imports an LLM provider, and no model output can suppress a rule that
has fired. If every model in the stack is unavailable, red flags still work —
that is the point of them.

Each rule is a pure function of the normalised case, so each is unit-testable
and reviewable by a clinician who does not read Python well. A rule that fires
always produces an immediate-referral banner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class Urgency(str, Enum):
    #: Call an ambulance / send now, do not complete the consultation first.
    immediate = "immediate"
    #: Refer today.
    same_day = "same_day"
    #: Refer, but the patient can travel in the next day or two.
    urgent = "urgent"


@dataclass(frozen=True)
class RedFlag:
    code: str
    urgency: Urgency
    #: Shown to the clinician, in their language.
    message_uz: str
    message_ru: str
    message_en: str
    #: Where to send the patient.
    refer_to: str
    #: Which inputs made this fire, for the audit trail and the UI.
    triggered_by: tuple[str, ...] = field(default=())

    def message(self, language: str) -> str:
        return {"uz": self.message_uz, "ru": self.message_ru}.get(language, self.message_en)


#: A specialised concept satisfies a rule written against its general one.
#:
#: The terminology map prefers the longest match, so "bolada ich ketishi"
#: yields `pediatric_diarrhea` and never `diarrhea` — which silently broke the
#: childhood-dehydration rule in Uzbek while it worked in Russian, where the
#: text says plain "диарея". The evaluation suite caught it; this table is the
#: fix, and it also makes rules robust to future vocabulary refinements.
CONCEPT_IMPLIES: dict[str, tuple[str, ...]] = {
    "pediatric_diarrhea": ("diarrhea",),
    "bloody_diarrhea": ("diarrhea",),
    "productive_cough": ("cough",),
    "dry_cough": ("cough",),
    "exertional_dyspnea": ("dyspnea",),
    "crushing_chest_pain": ("chest_pain",),
    "thunderclap_headache": ("headache",),
    "febrile_seizure": ("seizure",),
    "low_grade_fever": ("fever",),
    "myocardial_infarction": ("chest_pain",),
}


def expand_concepts(concepts: set[str]) -> set[str]:
    """Add the general concepts implied by any specialised ones present."""
    expanded = set(concepts)
    for concept in concepts:
        expanded.update(CONCEPT_IMPLIES.get(concept, ()))
    return expanded


@dataclass
class CaseFacts:
    """Everything a rule may look at. Deliberately flat and explicit."""

    concepts: set[str]
    age_years: float | None = None
    age_band: str = "unknown"
    sex: str = "unknown"
    pregnant: bool = False
    temperature_c: float | None = None
    pulse_bpm: int | None = None
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    respiratory_rate: int | None = None
    spo2: int | None = None
    weight_kg: float | None = None
    glucose_mmol: float | None = None
    duration_days: float | None = None
    free_text: str = ""

    def __post_init__(self) -> None:
        self.concepts = expand_concepts(self.concepts)

    def has(self, *concepts: str) -> bool:
        return any(c in self.concepts for c in concepts)

    def has_all(self, *concepts: str) -> bool:
        return all(c in self.concepts for c in concepts)


Rule = Callable[[CaseFacts], RedFlag | None]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _flag(
    code: str,
    urgency: Urgency,
    uz: str,
    ru: str,
    en: str,
    refer_to: str,
    triggered_by: tuple[str, ...],
) -> RedFlag:
    return RedFlag(
        code=code,
        urgency=urgency,
        message_uz=uz,
        message_ru=ru,
        message_en=en,
        refer_to=refer_to,
        triggered_by=triggered_by,
    )


# --- cardiorespiratory ---------------------------------------------------


@rule
def acute_coronary_syndrome(facts: CaseFacts) -> RedFlag | None:
    """Chest pain with dyspnea, or crushing chest pain alone."""
    if facts.has("crushing_chest_pain", "myocardial_infarction") or (
        facts.has("chest_pain") and facts.has("dyspnea", "sweating", "syncope")
    ):
        return _flag(
            "acs_suspected",
            Urgency.immediate,
            "Yurak xurujii shubhasi. Zudlik bilan tez yordam chaqiring, aspirin 300 mg chaynatib bering (allergiya bo'lmasa).",
            "Подозрение на инфаркт. Немедленно вызовите скорую, дайте разжевать аспирин 300 мг (при отсутствии аллергии).",
            "Suspected acute coronary syndrome. Call an ambulance now; give aspirin 300 mg chewed unless contraindicated.",
            "emergency_cardiology",
            ("chest_pain", "dyspnea"),
        )
    return None


@rule
def hypoxia(facts: CaseFacts) -> RedFlag | None:
    if facts.spo2 is not None and facts.spo2 < 92:
        return _flag(
            "hypoxia",
            Urgency.immediate,
            f"Kislorod darajasi past (SpO2 {facts.spo2}%). Kislorod bering va zudlik bilan yo'naltiring.",
            f"Низкая сатурация (SpO2 {facts.spo2}%). Дайте кислород и срочно направьте.",
            f"Hypoxia (SpO2 {facts.spo2}%). Give oxygen and refer immediately.",
            "emergency",
            ("spo2",),
        )
    return None


@rule
def respiratory_distress(facts: CaseFacts) -> RedFlag | None:
    if facts.respiratory_rate is not None and facts.respiratory_rate >= 30:
        return _flag(
            "respiratory_distress",
            Urgency.immediate,
            f"Nafas olish tezligi juda yuqori ({facts.respiratory_rate}/daq). Shoshilinch yo'naltiring.",
            f"Тахипноэ ({facts.respiratory_rate}/мин). Срочное направление.",
            f"Respiratory distress ({facts.respiratory_rate}/min). Refer immediately.",
            "emergency",
            ("respiratory_rate",),
        )
    if facts.has("choking"):
        return _flag(
            "airway_compromise",
            Urgency.immediate,
            "Nafas yo'llari xavf ostida. Zudlik bilan tez yordam.",
            "Угроза проходимости дыхательных путей. Немедленно скорая помощь.",
            "Airway compromise. Emergency referral now.",
            "emergency",
            ("choking",),
        )
    return None


# --- sepsis --------------------------------------------------------------


@rule
def sepsis(facts: CaseFacts) -> RedFlag | None:
    """qSOFA-style screen: any two of altered mentation, low BP, tachypnea,
    alongside suspected infection."""
    infection = facts.has(
        "fever", "pneumonia", "sepsis", "purulent_discharge", "bloody_diarrhea", "dysuria"
    ) or (facts.temperature_c is not None and facts.temperature_c >= 38.0)
    if not infection:
        return None

    criteria = []
    if facts.systolic_bp is not None and facts.systolic_bp <= 100:
        criteria.append("systolic_bp")
    if facts.respiratory_rate is not None and facts.respiratory_rate >= 22:
        criteria.append("respiratory_rate")
    if facts.has("lethargy", "seizure", "syncope"):
        criteria.append("altered_mentation")
    if facts.pulse_bpm is not None and facts.pulse_bpm >= 120:
        criteria.append("tachycardia")

    if len(criteria) >= 2:
        return _flag(
            "sepsis_suspected",
            Urgency.immediate,
            "Sepsis shubhasi. Zudlik bilan yo'naltiring; iloji bo'lsa suyuqlik va antibiotik boshlang.",
            "Подозрение на сепсис. Срочное направление; при возможности начните инфузию и антибиотик.",
            "Suspected sepsis. Refer immediately; start fluids and antibiotics if you can.",
            "emergency",
            tuple(criteria),
        )
    return None


# --- neurological --------------------------------------------------------


@rule
def stroke_fast(facts: CaseFacts) -> RedFlag | None:
    if facts.has("unilateral_weakness", "slurred_speech", "stroke"):
        return _flag(
            "stroke_fast",
            Urgency.immediate,
            "Insult belgilari (FAST). Vaqt — miya. Zudlik bilan insult markaziga yo'naltiring.",
            "Признаки инсульта (FAST). Время — мозг. Срочно в инсультный центр.",
            "Stroke signs (FAST). Time is brain. Refer to a stroke centre immediately.",
            "emergency_neurology",
            ("unilateral_weakness", "slurred_speech"),
        )
    return None


@rule
def meningism(facts: CaseFacts) -> RedFlag | None:
    signs = [
        c for c in ("neck_stiffness", "photophobia", "thunderclap_headache") if c in facts.concepts
    ]
    febrile = facts.has("fever") or (
        facts.temperature_c is not None and facts.temperature_c >= 38.0
    )
    if ("neck_stiffness" in facts.concepts and (febrile or len(signs) >= 2)) or len(signs) >= 2:
        return _flag(
            "meningism",
            Urgency.immediate,
            "Meningit shubhasi. Zudlik bilan yo'naltiring; birinchi doza antibiotikni kechiktirmang.",
            "Подозрение на менингит. Срочное направление; не откладывайте первую дозу антибиотика.",
            "Suspected meningitis. Refer immediately; do not delay the first antibiotic dose.",
            "emergency",
            tuple(signs),
        )
    return None


@rule
def seizure(facts: CaseFacts) -> RedFlag | None:
    if facts.has("seizure") and facts.age_band not in ("infant", "under5"):
        return _flag(
            "seizure",
            Urgency.same_day,
            "Talvasa. Sababini aniqlash uchun yo'naltiring.",
            "Судороги. Направьте для установления причины.",
            "Seizure. Refer for investigation of the cause.",
            "neurology",
            ("seizure",),
        )
    return None


# --- pediatric -----------------------------------------------------------


@rule
def pediatric_danger_signs(facts: CaseFacts) -> RedFlag | None:
    """WHO IMCI general danger signs in a child under five."""
    if facts.age_band not in ("infant", "under5"):
        return None
    signs = [
        c
        for c in ("unable_to_feed", "lethargy", "febrile_seizure", "seizure", "dehydration")
        if c in facts.concepts
    ]
    if signs:
        return _flag(
            "imci_danger_sign",
            Urgency.immediate,
            "IMCI xavf belgisi (bolada). Pre-referal davolashdan keyin zudlik bilan shifoxonaga yo'naltiring.",
            "Общий признак опасности по IMCI у ребёнка. После пререферальной помощи — срочно в стационар.",
            "IMCI general danger sign in a child. Give pre-referral treatment and refer urgently.",
            "pediatric_emergency",
            tuple(signs),
        )
    return None


@rule
def pediatric_severe_dehydration(facts: CaseFacts) -> RedFlag | None:
    if facts.age_band in ("infant", "under5") and facts.has_all("diarrhea", "dehydration"):
        return _flag(
            "pediatric_dehydration",
            Urgency.immediate,
            "Bolada suvsizlanish bilan ich ketishi. Plan C bo'yicha suyuqlik bering va yo'naltiring.",
            "Диарея с обезвоживанием у ребёнка. Начните План C и направьте.",
            "Childhood diarrhoea with dehydration. Start Plan C fluids and refer.",
            "pediatric_emergency",
            ("diarrhea", "dehydration"),
        )
    return None


# --- obstetric -----------------------------------------------------------


@rule
def pregnancy_bleeding(facts: CaseFacts) -> RedFlag | None:
    if facts.has("pregnancy_bleeding") or (
        facts.pregnant and facts.has("hematuria", "abdominal_pain")
    ):
        return _flag(
            "pregnancy_bleeding",
            Urgency.immediate,
            "Homiladorlikda qon ketishi yoki og'riq. Zudlik bilan akusherlik yordamiga yo'naltiring.",
            "Кровотечение или боль при беременности. Срочно в родовспоможение.",
            "Bleeding or pain in pregnancy. Refer to obstetric care immediately.",
            "obstetrics",
            ("pregnancy_bleeding",),
        )
    return None


@rule
def preeclampsia(facts: CaseFacts) -> RedFlag | None:
    if facts.pregnant and facts.systolic_bp is not None and facts.systolic_bp >= 140:
        return _flag(
            "preeclampsia_suspected",
            Urgency.immediate,
            "Homiladorlikda yuqori bosim — preeklampsiya shubhasi. Zudlik bilan yo'naltiring.",
            "Высокое давление при беременности — подозрение на преэклампсию. Срочное направление.",
            "Raised blood pressure in pregnancy — suspected pre-eclampsia. Refer immediately.",
            "obstetrics",
            ("systolic_bp", "pregnancy"),
        )
    return None


# --- gastrointestinal / bleeding ----------------------------------------


@rule
def gi_bleeding(facts: CaseFacts) -> RedFlag | None:
    signs = [c for c in ("hematemesis", "melena", "bloody_diarrhea") if c in facts.concepts]
    if signs:
        return _flag(
            "gi_bleeding",
            Urgency.immediate,
            "Oshqozon-ichak qon ketishi belgilari. Zudlik bilan yo'naltiring.",
            "Признаки желудочно-кишечного кровотечения. Срочное направление.",
            "Signs of gastrointestinal bleeding. Refer immediately.",
            "emergency_surgery",
            tuple(signs),
        )
    return None


@rule
def hemoptysis(facts: CaseFacts) -> RedFlag | None:
    if facts.has("hemoptysis"):
        return _flag(
            "hemoptysis",
            Urgency.same_day,
            "Balg'amda qon. Sil va o'sma istisno qilinishi kerak — balg'am tekshiruvi va rentgen.",
            "Кровь в мокроте. Исключить туберкулёз и опухоль — анализ мокроты и рентген.",
            "Haemoptysis. Exclude tuberculosis and malignancy — sputum testing and chest X-ray.",
            "tb_service",
            ("hemoptysis",),
        )
    return None


# --- infectious ----------------------------------------------------------


@rule
def tb_triad(facts: CaseFacts) -> RedFlag | None:
    """Cough over three weeks with night sweats or weight loss."""
    prolonged_cough = facts.has("cough") and (
        facts.has("onset_over_3w")
        or (facts.duration_days is not None and facts.duration_days >= 21)
    )
    if prolonged_cough and facts.has("night_sweats", "weight_loss", "hemoptysis"):
        return _flag(
            "tb_suspected",
            Urgency.urgent,
            "Sil kasalligiga shubha. Balg'amni GeneXpert ga yuboring, niqob bering, sil xizmatiga yo'naltiring. Davolashni o'zingiz boshlamang.",
            "Подозрение на туберкулёз. Мокрота на GeneXpert, маска пациенту, направление в противотуберкулёзную службу. Лечение не начинать самостоятельно.",
            "Suspected tuberculosis. Send sputum for GeneXpert, mask the patient, refer to the TB service. Do not start treatment yourself.",
            "tb_service",
            ("cough", "night_sweats"),
        )
    return None


# --- metabolic -----------------------------------------------------------


@rule
def hyperglycemic_emergency(facts: CaseFacts) -> RedFlag | None:
    if facts.glucose_mmol is not None and facts.glucose_mmol >= 20:
        return _flag(
            "hyperglycemic_emergency",
            Urgency.immediate,
            f"Qon glyukozasi juda yuqori ({facts.glucose_mmol} mmol/l). Ketoatsidoz xavfi — zudlik bilan yo'naltiring.",
            f"Очень высокая глюкоза ({facts.glucose_mmol} ммоль/л). Риск кетоацидоза — срочное направление.",
            f"Severe hyperglycaemia ({facts.glucose_mmol} mmol/L). Risk of ketoacidosis — refer immediately.",
            "emergency",
            ("glucose_mmol",),
        )
    if facts.glucose_mmol is not None and facts.glucose_mmol < 3.0:
        return _flag(
            "hypoglycemia",
            Urgency.immediate,
            f"Gipoglikemiya ({facts.glucose_mmol} mmol/l). Darhol shakar bering va yo'naltiring.",
            f"Гипогликемия ({facts.glucose_mmol} ммоль/л). Немедленно дайте сахар и направьте.",
            f"Hypoglycaemia ({facts.glucose_mmol} mmol/L). Give sugar now and refer.",
            "emergency",
            ("glucose_mmol",),
        )
    return None


@rule
def hypertensive_emergency(facts: CaseFacts) -> RedFlag | None:
    severe = (facts.systolic_bp is not None and facts.systolic_bp >= 180) or (
        facts.diastolic_bp is not None and facts.diastolic_bp >= 110
    )
    symptomatic = facts.has(
        "chest_pain", "dyspnea", "thunderclap_headache", "blurred_vision", "unilateral_weakness"
    )
    if severe and symptomatic:
        return _flag(
            "hypertensive_emergency",
            Urgency.immediate,
            "Gipertonik kriz belgilari bilan. Bosimni birlamchi bo'g'inda tez tushirmang — zudlik bilan yo'naltiring.",
            "Гипертонический криз с симптомами. Не снижайте давление быстро на первичном уровне — срочное направление.",
            "Hypertensive emergency. Do not reduce blood pressure rapidly in primary care — refer immediately.",
            "emergency",
            ("systolic_bp", "symptoms"),
        )
    return None


@rule
def severe_anemia(facts: CaseFacts) -> RedFlag | None:
    if facts.has("anemia", "pallor") and facts.has("dyspnea", "syncope", "chest_pain"):
        return _flag(
            "severe_anemia",
            Urgency.same_day,
            "Og'ir kamqonlik belgilari. Temir preparati bilan cheklanmang — yo'naltiring.",
            "Признаки тяжёлой анемии. Не ограничивайтесь препаратами железа — направьте.",
            "Signs of severe anaemia. Do not simply prescribe iron — refer.",
            "internal_medicine",
            ("anemia", "dyspnea"),
        )
    return None


def evaluate(facts: CaseFacts) -> list[RedFlag]:
    """Run every rule. Order of the result is by urgency, most urgent first."""
    fired = [flag for check in RULES for flag in (check(facts),) if flag is not None]
    order = {Urgency.immediate: 0, Urgency.same_day: 1, Urgency.urgent: 2}
    return sorted(fired, key=lambda f: order[f.urgency])


def highest_urgency(flags: list[RedFlag]) -> Urgency | None:
    return flags[0].urgency if flags else None
