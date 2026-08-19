'use client';

import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { api, type AuditVerification } from '@/lib/api';
import { t } from '@/lib/i18n';

export default function AuditPage() {
  const { language } = useLanguage();
  const [state, setState] = useState<AuditVerification | null>(null);
  const [error, setError] = useState<string | null>(null);

  const verify = useCallback(async () => {
    setError(null);
    try {
      setState(await api.verifyAudit());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void verify();
  }, [verify]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold">{t('audit.title', language)}</h1>

      <p className="mb-6 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
        {/* This page is the regulatory sandbox evidence: the export is what a
            reviewer receives, and the chain check is what proves it is intact. */}
        {language === 'ru'
          ? 'Журнал аудита защищён хеш-цепочкой: изменение любой строки нарушает все последующие хеши. Экспорт не содержит идентификаторов пациентов.'
          : 'Audit jurnali xesh-zanjir bilan himoyalangan: bitta yozuvni o‘zgartirish keyingi barcha xeshlarni buzadi. Eksportda bemor identifikatorlari yo‘q.'}
      </p>

      {error ? <p className="text-danger">{error}</p> : null}
      {state === null && !error ? <p>{t('common.loading', language)}</p> : null}

      {state ? (
        <div
          className={`mb-6 rounded-lg border p-4 ${
            state.ok
              ? 'border-ok bg-emerald-50 dark:bg-emerald-950/30'
              : 'border-danger bg-red-50 dark:bg-red-950/30'
          }`}
        >
          <div className={`text-lg font-semibold ${state.ok ? 'text-ok' : 'text-danger'}`}>
            {t(state.ok ? 'audit.verified' : 'audit.broken', language)}
          </div>
          <div className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            {t('audit.entries', language)}: {state.entries}
            {state.problem ? ` · ${state.problem}` : ''}
          </div>
        </div>
      ) : null}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => void verify()}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm dark:border-slate-700"
        >
          {t('audit.verify', language)}
        </button>
        <a
          href={api.auditExportUrl()}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white"
        >
          {t('audit.export', language)}
        </a>
      </div>
    </div>
  );
}
