/**
 * Admin UI strings.
 *
 * Uzbek and Russian only on operational surfaces — a clinic administrator in
 * Chinoz does not read English. Developer-only labels may stay in English.
 * `strings.test` asserts the two tables have identical keys.
 */
export type Language = 'uz' | 'ru';

export const uz = {
  'nav.dashboard': 'Boshqaruv paneli',
  'nav.clinics': 'Klinikalar',
  'nav.audit': 'Audit jurnali',
  'dash.title': 'Klinikalar bo‘yicha ko‘rsatkichlar',
  'dash.period': 'Davr',
  'dash.days30': '30 kun',
  'dash.days7': '7 kun',
  'dash.consultations': 'Qabullar',
  'dash.acceptance': 'AI takliflarini qabul qilish',
  'dash.acceptanceHint': 'Asosiy mahsulot ko‘rsatkichi',
  'dash.edited': 'Tahrirlangan',
  'dash.rejected': 'Rad etilgan',
  'dash.undecided': 'Qaror qabul qilinmagan',
  'dash.undecidedHint': 'Shifokor ko‘rigi kutilmoqda',
  'dash.redFlags': 'Xavfli belgilar',
  'dash.cost': 'Xarajat',
  'dash.latency': 'O‘rtacha javob vaqti',
  'dash.degraded': 'Zaxira rejimda',
  'dash.offline': 'Oflayn yaratilgan',
  'dash.conflicts': 'Sinxronizatsiya nizolari',
  'dash.empty': 'Ma’lumot yo‘q',
  'clinic.name': 'Klinika',
  'clinic.region': 'Viloyat',
  'clinic.tier': 'Daraja',
  'clinic.new': 'Yangi klinika',
  'clinic.users': 'Xodimlarni qo‘shish',
  'audit.title': 'Audit jurnali',
  'audit.verify': 'Zanjirni tekshirish',
  'audit.export': 'CSV yuklab olish',
  'audit.verified': 'Audit zanjiri butun',
  'audit.broken': 'DIQQAT: audit zanjiri buzilgan',
  'audit.entries': 'Yozuvlar',
  'common.loading': 'Yuklanmoqda…',
  'common.error': 'Xatolik yuz berdi',
  'common.retry': 'Qayta urinish',
  'common.language': 'Til',
} as const;

export type StringKey = keyof typeof uz;

export const ru: Record<StringKey, string> = {
  'nav.dashboard': 'Панель управления',
  'nav.clinics': 'Клиники',
  'nav.audit': 'Журнал аудита',
  'dash.title': 'Показатели по клиникам',
  'dash.period': 'Период',
  'dash.days30': '30 дней',
  'dash.days7': '7 дней',
  'dash.consultations': 'Приёмы',
  'dash.acceptance': 'Принятие предложений ИИ',
  'dash.acceptanceHint': 'Ключевая продуктовая метрика',
  'dash.edited': 'Изменено',
  'dash.rejected': 'Отклонено',
  'dash.undecided': 'Без решения',
  'dash.undecidedHint': 'Ожидает проверки врача',
  'dash.redFlags': 'Тревожные признаки',
  'dash.cost': 'Стоимость',
  'dash.latency': 'Среднее время ответа',
  'dash.degraded': 'В резервном режиме',
  'dash.offline': 'Создано офлайн',
  'dash.conflicts': 'Конфликты синхронизации',
  'dash.empty': 'Нет данных',
  'clinic.name': 'Клиника',
  'clinic.region': 'Область',
  'clinic.tier': 'Уровень',
  'clinic.new': 'Новая клиника',
  'clinic.users': 'Добавить сотрудников',
  'audit.title': 'Журнал аудита',
  'audit.verify': 'Проверить цепочку',
  'audit.export': 'Скачать CSV',
  'audit.verified': 'Цепочка аудита цела',
  'audit.broken': 'ВНИМАНИЕ: цепочка аудита нарушена',
  'audit.entries': 'Записи',
  'common.loading': 'Загрузка…',
  'common.error': 'Произошла ошибка',
  'common.retry': 'Повторить',
  'common.language': 'Язык',
};

export function t(key: StringKey, language: Language): string {
  return (language === 'ru' ? ru : uz)[key];
}
