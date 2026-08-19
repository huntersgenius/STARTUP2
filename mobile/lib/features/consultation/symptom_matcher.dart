/// On-device symptom-to-concept matching.
///
/// A compact subset of `knowledge/terminology.csv` — the terms needed by the
/// local red-flag rules and by symptom chips. The full 481-surface map stays
/// on the server; shipping all of it to the tablet would bloat the app without
/// helping, because the offline path only needs the dangerous subset.
library;

/// concept → surfaces a clinician might type, in Uzbek and Russian.
const Map<String, List<String>> kLocalTerms = <String, List<String>>{
  'chest_pain': [
    'ko\'krak og\'rig\'i',
    'kokrak ogrigi',
    'ko\'kragim og\'riyapti',
    'боль в груди'
  ],
  'crushing_chest_pain': [
    'yurak siqishi',
    'ko\'krak siqilishi',
    'сжимающая боль в груди'
  ],
  'dyspnea': ['nafas qisishi', 'nafas qisish', 'hansirash', 'одышка'],
  'cough': ['yo\'tal', 'yotal', 'yo\'talyapti', 'кашель'],
  'fever': ['isitma', 'harorat', 'qizitma', 'температура'],
  'night_sweats': ['tunda terlash', 'kechasi terlayman', 'ночная потливость'],
  'weight_loss': ['ozish', 'ozib ketdim', 'vazn yo\'qotish', 'потеря веса'],
  'hemoptysis': ['qonli balg\'am', 'qon tupurish', 'кровь в мокроте'],
  'diarrhea': ['ich ketishi', 'ich ketdi', 'ichim ketyapti', 'диарея', 'понос'],
  'dehydration': ['suvsizlanish', 'ko\'zi ichiga botgan', 'обезвоживание'],
  'unable_to_feed': ['emmayapti', 'ko\'krak emmaydi', 'не сосёт'],
  'lethargy': ['letargik', 'bo\'shashgan', 'uyg\'onmayapti', 'вялый'],
  'seizure': ['talvasa', 'tirishish', 'судороги'],
  'febrile_seizure': ['bolada talvasa', 'судороги у ребёнка'],
  'neck_stiffness': ['bo\'yin qotishi', 'bo\'yin qattiq', 'ригидность затылка'],
  'photophobia': ['yorug\'likdan qo\'rqish', 'светобоязнь'],
  'thunderclap_headache': [
    'kuchli bosh og\'rig\'i',
    'сильнейшая головная боль'
  ],
  'unilateral_weakness': [
    'bir tomon holsizligi',
    'yuzi qiyshaygan',
    'слабость в одной стороне'
  ],
  'slurred_speech': ['nutq buzilishi', 'tili tutildi', 'нарушение речи'],
  'stroke': ['insult', 'инсульт'],
  'hematemesis': ['qonli qusish', 'qon qusish', 'рвота с кровью'],
  'melena': ['qora najas', 'чёрный стул'],
  'bloody_diarrhea': ['qonli ich ketishi', 'najasda qon', 'кровь в стуле'],
  'pregnancy_bleeding': [
    'homiladorlikda qon ketishi',
    'кровотечение при беременности'
  ],
  'pregnancy': ['homiladorlik', 'homilador', 'беременность'],
  'syncope': ['hushdan ketish', 'обморок'],
  'sweating': ['terlash', 'ter bosishi', 'потливость'],
  'headache': ['bosh og\'rig\'i', 'bosh ogrigi', 'головная боль'],
  'abdominal_pain': ['qorin og\'rig\'i', 'qorin ogrigi', 'боль в животе'],
  'vomiting': ['qusish', 'рвота'],
  'nausea': ['ko\'ngil aynishi', 'kongim aynyapti', 'тошнота'],
  'sore_throat': ['tomoq og\'rig\'i', 'боль в горле'],
  'rash': ['toshma', 'сыпь'],
  'weakness': ['holsizlik', 'darmonsizlik', 'слабость'],
  'dizziness': ['bosh aylanishi', 'головокружение'],
  'onset_over_3w': [
    'uch haftadan ortiq',
    'более трёх недель',
    '3 haftadan ko\'p'
  ],
};

/// Chips offered on the symptom entry screen, in presentation order.
const List<String> kSymptomChips = <String>[
  'fever',
  'cough',
  'dyspnea',
  'chest_pain',
  'abdominal_pain',
  'diarrhea',
  'vomiting',
  'headache',
  'sore_throat',
  'rash',
  'weakness',
  'dizziness',
];

const Map<String, String> kConceptLabelsUz = <String, String>{
  'fever': 'Isitma',
  'cough': 'Yo\'tal',
  'dyspnea': 'Nafas qisishi',
  'chest_pain': 'Ko\'krak og\'rig\'i',
  'abdominal_pain': 'Qorin og\'rig\'i',
  'diarrhea': 'Ich ketishi',
  'vomiting': 'Qusish',
  'headache': 'Bosh og\'rig\'i',
  'sore_throat': 'Tomoq og\'rig\'i',
  'rash': 'Toshma',
  'weakness': 'Holsizlik',
  'dizziness': 'Bosh aylanishi',
};

const Map<String, String> kConceptLabelsRu = <String, String>{
  'fever': 'Температура',
  'cough': 'Кашель',
  'dyspnea': 'Одышка',
  'chest_pain': 'Боль в груди',
  'abdominal_pain': 'Боль в животе',
  'diarrhea': 'Диарея',
  'vomiting': 'Рвота',
  'headache': 'Головная боль',
  'sore_throat': 'Боль в горле',
  'rash': 'Сыпь',
  'weakness': 'Слабость',
  'dizziness': 'Головокружение',
};

String conceptLabel(String concept, String language) {
  final Map<String, String> labels =
      language == 'ru' ? kConceptLabelsRu : kConceptLabelsUz;
  return labels[concept] ?? concept.replaceAll('_', ' ');
}

/// Apostrophe variants a phone, a laptop and OCR each produce differently.
const String _apostrophes = '’‘ʻʼ`´\'';

String normalizeSymptomText(String text) {
  String result = text.toLowerCase();
  for (final String ch in _apostrophes.split('')) {
    result = result.replaceAll(ch, '');
  }
  return result.replaceAll(RegExp(r'\s+'), ' ').trim();
}

/// Longest surface first, so "qonli ich ketishi" wins over "ich ketishi".
final List<MapEntry<String, String>> _index = () {
  final List<MapEntry<String, String>> entries = <MapEntry<String, String>>[];
  kLocalTerms.forEach((concept, surfaces) {
    for (final String surface in surfaces) {
      entries.add(
          MapEntry<String, String>(normalizeSymptomText(surface), concept));
    }
  });
  entries.sort((a, b) => b.key.length.compareTo(a.key.length));
  return entries;
}();

/// Extract concepts from free text typed by a clinician.
Set<String> extractConcepts(String text) {
  final String haystack = normalizeSymptomText(text);
  final Set<String> found = <String>{};
  final List<List<int>> claimed = <List<int>>[];

  for (final MapEntry<String, String> entry in _index) {
    int from = 0;
    while (true) {
      final int at = haystack.indexOf(entry.key, from);
      if (at == -1) break;
      final int end = at + entry.key.length;
      from = at + 1;
      final bool overlaps = claimed.any((r) => at < r[1] && r[0] < end);
      if (overlaps) continue;
      claimed.add(<int>[at, end]);
      found.add(entry.value);
    }
  }
  return found;
}

/// Numeric findings mean something on their own — mirrors the server's
/// `numeric_concepts`. A blood pressure of 160/95 is hypertension whether or
/// not anyone typed the word.
Set<String> conceptsFromVitals(Map<String, dynamic> vitals) {
  final Set<String> found = <String>{};
  final num? temperature = vitals['temperature_c'] as num?;
  if (temperature != null && temperature >= 38.0) found.add('fever');
  final num? systolic = vitals['systolic_bp'] as num?;
  final num? diastolic = vitals['diastolic_bp'] as num?;
  if ((systolic != null && systolic >= 140) ||
      (diastolic != null && diastolic >= 90)) {
    found.add('hypertension');
  }
  final num? spo2 = vitals['spo2'] as num?;
  if (spo2 != null && spo2 < 92) found.add('dyspnea');
  return found;
}
