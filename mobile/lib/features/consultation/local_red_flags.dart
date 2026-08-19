/// Red-flag rules that run on the device.
///
/// A mirror of `backend/app/ai/red_flags.py` for the subset that needs no
/// retrieval. The duplication is deliberate and load-bearing: a feldsher with
/// no signal must still get the immediate-referral banner for a chest pain
/// with breathlessness. `test/local_red_flags_test.dart` checks this list
/// against the codes the server produces, so the two cannot drift silently.
library;

class LocalRedFlag {
  const LocalRedFlag({
    required this.code,
    required this.urgency,
    required this.messageUz,
    required this.messageRu,
    required this.referTo,
  });

  final String code;
  final String urgency;
  final String messageUz;
  final String messageRu;
  final String referTo;

  bool get isImmediate => urgency == 'immediate';

  String message(String language) => language == 'ru' ? messageRu : messageUz;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'code': code,
        'urgency': urgency,
        'message': messageUz,
        'refer_to': referTo,
        'triggered_by': <String>[],
      };
}

class LocalCase {
  const LocalCase({
    required this.concepts,
    this.ageYears,
    this.pregnant = false,
    this.temperatureC,
    this.systolicBp,
    this.diastolicBp,
    this.respiratoryRate,
    this.spo2,
    this.glucoseMmol,
    this.durationDays,
  });

  final Set<String> concepts;
  final double? ageYears;
  final bool pregnant;
  final double? temperatureC;
  final int? systolicBp;
  final int? diastolicBp;
  final int? respiratoryRate;
  final int? spo2;
  final double? glucoseMmol;
  final double? durationDays;

  bool get isChild => ageYears != null && ageYears! < 5;
  bool has(List<String> any) => any.any(concepts.contains);
}

const LocalRedFlag _acs = LocalRedFlag(
  code: 'acs_suspected',
  urgency: 'immediate',
  messageUz:
      'Yurak xurujii shubhasi. Zudlik bilan tez yordam chaqiring, aspirin 300 mg chaynatib bering (allergiya bo\'lmasa).',
  messageRu:
      'Подозрение на инфаркт. Немедленно вызовите скорую, дайте разжевать аспирин 300 мг (при отсутствии аллергии).',
  referTo: 'emergency_cardiology',
);

const LocalRedFlag _stroke = LocalRedFlag(
  code: 'stroke_fast',
  urgency: 'immediate',
  messageUz:
      'Insult belgilari (FAST). Vaqt — miya. Zudlik bilan yo\'naltiring.',
  messageRu: 'Признаки инсульта (FAST). Время — мозг. Срочное направление.',
  referTo: 'emergency_neurology',
);

const LocalRedFlag _meningism = LocalRedFlag(
  code: 'meningism',
  urgency: 'immediate',
  messageUz: 'Meningit shubhasi. Zudlik bilan yo\'naltiring.',
  messageRu: 'Подозрение на менингит. Срочное направление.',
  referTo: 'emergency',
);

const LocalRedFlag _hypoxia = LocalRedFlag(
  code: 'hypoxia',
  urgency: 'immediate',
  messageUz:
      'Kislorod darajasi past. Kislorod bering va zudlik bilan yo\'naltiring.',
  messageRu: 'Низкая сатурация. Дайте кислород и срочно направьте.',
  referTo: 'emergency',
);

const LocalRedFlag _imci = LocalRedFlag(
  code: 'imci_danger_sign',
  urgency: 'immediate',
  messageUz:
      'IMCI xavf belgisi (bolada). Zudlik bilan shifoxonaga yo\'naltiring.',
  messageRu: 'Признак опасности IMCI у ребёнка. Срочно в стационар.',
  referTo: 'pediatric_emergency',
);

const LocalRedFlag _pediatricDehydration = LocalRedFlag(
  code: 'pediatric_dehydration',
  urgency: 'immediate',
  messageUz: 'Bolada suvsizlanish bilan ich ketishi. Plan C va yo\'naltirish.',
  messageRu: 'Диарея с обезвоживанием у ребёнка. План C и направление.',
  referTo: 'pediatric_emergency',
);

const LocalRedFlag _pregnancyBleeding = LocalRedFlag(
  code: 'pregnancy_bleeding',
  urgency: 'immediate',
  messageUz: 'Homiladorlikda qon ketishi. Zudlik bilan akusherlik yordamiga.',
  messageRu: 'Кровотечение при беременности. Срочно в родовспоможение.',
  referTo: 'obstetrics',
);

const LocalRedFlag _preeclampsia = LocalRedFlag(
  code: 'preeclampsia_suspected',
  urgency: 'immediate',
  messageUz: 'Homiladorlikda yuqori bosim — preeklampsiya shubhasi.',
  messageRu: 'Высокое давление при беременности — подозрение на преэклампсию.',
  referTo: 'obstetrics',
);

const LocalRedFlag _giBleeding = LocalRedFlag(
  code: 'gi_bleeding',
  urgency: 'immediate',
  messageUz: 'Oshqozon-ichak qon ketishi. Zudlik bilan yo\'naltiring.',
  messageRu: 'Желудочно-кишечное кровотечение. Срочное направление.',
  referTo: 'emergency_surgery',
);

const LocalRedFlag _tb = LocalRedFlag(
  code: 'tb_suspected',
  urgency: 'urgent',
  messageUz:
      'Sil kasalligiga shubha. Balg\'am tekshiruvi va sil xizmatiga yo\'naltirish. Davolashni boshlamang.',
  messageRu:
      'Подозрение на туберкулёз. Анализ мокроты и направление в противотуберкулёзную службу. Лечение не начинать.',
  referTo: 'tb_service',
);

const LocalRedFlag _hypoglycemia = LocalRedFlag(
  code: 'hypoglycemia',
  urgency: 'immediate',
  messageUz: 'Gipoglikemiya. Darhol shakar bering va yo\'naltiring.',
  messageRu: 'Гипогликемия. Немедленно дайте сахар и направьте.',
  referTo: 'emergency',
);

const LocalRedFlag _hyperglycemia = LocalRedFlag(
  code: 'hyperglycemic_emergency',
  urgency: 'immediate',
  messageUz:
      'Qon glyukozasi juda yuqori. Ketoatsidoz xavfi — zudlik bilan yo\'naltiring.',
  messageRu: 'Очень высокая глюкоза. Риск кетоацидоза — срочное направление.',
  referTo: 'emergency',
);

/// Every rule the device evaluates. Order of evaluation does not matter; the
/// result is sorted by urgency.
List<LocalRedFlag> evaluateLocalRedFlags(LocalCase c) {
  final List<LocalRedFlag> fired = <LocalRedFlag>[];

  if (c.has(['crushing_chest_pain', 'myocardial_infarction']) ||
      (c.has(['chest_pain']) && c.has(['dyspnea', 'sweating', 'syncope']))) {
    fired.add(_acs);
  }
  if (c.has(['unilateral_weakness', 'slurred_speech', 'stroke'])) {
    fired.add(_stroke);
  }
  final bool febrile =
      c.has(['fever']) || (c.temperatureC != null && c.temperatureC! >= 38.0);
  final int meningealSigns = <String>[
    'neck_stiffness',
    'photophobia',
    'thunderclap_headache',
  ].where(c.concepts.contains).length;
  if ((c.concepts.contains('neck_stiffness') &&
          (febrile || meningealSigns >= 2)) ||
      meningealSigns >= 2) {
    fired.add(_meningism);
  }
  if (c.spo2 != null && c.spo2! < 92) {
    fired.add(_hypoxia);
  }
  if (c.isChild &&
      c.has([
        'unable_to_feed',
        'lethargy',
        'febrile_seizure',
        'seizure',
        'dehydration'
      ])) {
    fired.add(_imci);
  }
  if (c.isChild &&
      c.concepts.contains('diarrhea') &&
      c.concepts.contains('dehydration')) {
    fired.add(_pediatricDehydration);
  }
  if (c.concepts.contains('pregnancy_bleeding')) {
    fired.add(_pregnancyBleeding);
  }
  if (c.pregnant && c.systolicBp != null && c.systolicBp! >= 140) {
    fired.add(_preeclampsia);
  }
  if (c.has(['hematemesis', 'melena', 'bloody_diarrhea'])) {
    fired.add(_giBleeding);
  }
  final bool prolongedCough = c.concepts.contains('cough') &&
      (c.concepts.contains('onset_over_3w') ||
          (c.durationDays != null && c.durationDays! >= 21));
  if (prolongedCough && c.has(['night_sweats', 'weight_loss', 'hemoptysis'])) {
    fired.add(_tb);
  }
  if (c.glucoseMmol != null && c.glucoseMmol! < 3.0) {
    fired.add(_hypoglycemia);
  }
  if (c.glucoseMmol != null && c.glucoseMmol! >= 20.0) {
    fired.add(_hyperglycemia);
  }

  const Map<String, int> order = <String, int>{
    'immediate': 0,
    'same_day': 1,
    'urgent': 2,
  };
  fired
      .sort((a, b) => (order[a.urgency] ?? 3).compareTo(order[b.urgency] ?? 3));
  return fired;
}
