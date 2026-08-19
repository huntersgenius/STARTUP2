'use client';

import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { api, type Clinic } from '@/lib/api';
import { t } from '@/lib/i18n';

export default function ClinicsPage() {
  const { language } = useLanguage();
  const [clinics, setClinics] = useState<Clinic[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setClinics(await api.clinics());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold">{t('nav.clinics', language)}</h1>

      {error ? <p className="text-danger">{error}</p> : null}
      {clinics === null && !error ? <p>{t('common.loading', language)}</p> : null}

      {clinics ? (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700">
              <th className="py-2 pr-3">{t('clinic.name', language)}</th>
              <th className="py-2 pr-3">{t('clinic.region', language)}</th>
              <th className="py-2 pr-3 text-right">{t('clinic.tier', language)}</th>
              <th className="py-2 pr-3">Offline</th>
              <th className="py-2">{t('common.language', language)}</th>
            </tr>
          </thead>
          <tbody>
            {clinics.map((clinic) => (
              <tr key={clinic.id} className="border-b border-slate-200 dark:border-slate-800">
                <td className="py-2 pr-3 font-medium">{clinic.name}</td>
                <td className="py-2 pr-3">{clinic.region}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{clinic.tier}</td>
                <td className="py-2 pr-3">
                  {/* Offline-mode clinics run an edge server and expect long
                      disconnections; ops treats their sync backlog differently. */}
                  {clinic.offline_mode ? '✓' : '—'}
                </td>
                <td className="py-2">{clinic.default_language}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
