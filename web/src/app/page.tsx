'use client';

import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { StatTile } from '@/components/stat-tile';
import { api, formatMs, formatPercent, formatUsd, type ClinicMetrics } from '@/lib/api';
import { t } from '@/lib/i18n';

export default function DashboardPage() {
  const { language } = useLanguage();
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState<ClinicMetrics[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.metrics(days));
    } catch (cause) {
      setRows(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  // Aggregate across clinics: the superadmin view is a portfolio, not a list.
  const totals = (rows ?? []).reduce(
    (acc, row) => ({
      consultations: acc.consultations + row.consultations,
      offline: acc.offline + row.consultations_offline,
      decisions: acc.decisions + row.decisions,
      accepted: acc.accepted + (row.acceptance_rate ?? 0) * row.decisions,
      undecided: acc.undecided + row.undecided,
      redFlags: acc.redFlags + row.red_flags_fired,
      cost: acc.cost + row.total_cost_usd,
      conflicts: acc.conflicts + row.sync_conflicts,
    }),
    {
      consultations: 0,
      offline: 0,
      decisions: 0,
      accepted: 0,
      undecided: 0,
      redFlags: 0,
      cost: 0,
      conflicts: 0,
    },
  );
  const acceptance = totals.decisions ? totals.accepted / totals.decisions : null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('dash.title', language)}</h1>
        <div className="flex gap-2">
          {[7, 30].map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDays(option)}
              className={`rounded-md border px-3 py-1.5 text-sm ${
                days === option
                  ? 'border-brand bg-brand text-white'
                  : 'border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-400'
              }`}
            >
              {t(option === 7 ? 'dash.days7' : 'dash.days30', language)}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="rounded-md border border-danger bg-red-50 p-4 text-danger dark:bg-red-950/30">
          {t('common.error', language)}: {error}
          <button type="button" onClick={() => void load()} className="ml-3 underline">
            {t('common.retry', language)}
          </button>
        </div>
      ) : null}

      {rows === null && !error ? <p>{t('common.loading', language)}</p> : null}

      {rows ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile
              label={t('dash.acceptance', language)}
              value={formatPercent(acceptance)}
              hint={t('dash.acceptanceHint', language)}
              tone="ok"
            />
            <StatTile
              label={t('dash.consultations', language)}
              value={String(totals.consultations)}
              hint={`${t('dash.offline', language)}: ${totals.offline}`}
            />
            <StatTile
              label={t('dash.undecided', language)}
              value={String(totals.undecided)}
              hint={t('dash.undecidedHint', language)}
              tone={totals.undecided > 0 ? 'warn' : 'default'}
            />
            <StatTile
              label={t('dash.redFlags', language)}
              value={String(totals.redFlags)}
              tone={totals.redFlags > 0 ? 'danger' : 'default'}
            />
            <StatTile label={t('dash.cost', language)} value={formatUsd(totals.cost)} />
            <StatTile
              label={t('dash.conflicts', language)}
              value={String(totals.conflicts)}
              tone={totals.conflicts > 0 ? 'warn' : 'default'}
            />
          </div>

          <table className="mt-8 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-700">
                <th className="py-2 pr-3">{t('clinic.name', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.consultations', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.acceptance', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.edited', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.rejected', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.undecided', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.redFlags', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.latency', language)}</th>
                <th className="py-2 pr-3 text-right">{t('dash.degraded', language)}</th>
                <th className="py-2 text-right">{t('dash.cost', language)}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-6 text-center text-slate-500">
                    {t('dash.empty', language)}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr
                    key={row.clinic_id}
                    className="border-b border-slate-200 dark:border-slate-800"
                  >
                    <td className="py-2 pr-3 font-medium">{row.clinic_name}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{row.consultations}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatPercent(row.acceptance_rate)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatPercent(row.edit_rate)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatPercent(row.reject_rate)}
                    </td>
                    <td
                      className={`py-2 pr-3 text-right tabular-nums ${
                        row.undecided > 0 ? 'text-warn' : ''
                      }`}
                    >
                      {row.undecided}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{row.red_flags_fired}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatMs(row.mean_latency_ms)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatPercent(row.degraded_share)}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {formatUsd(row.total_cost_usd)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </>
      ) : null}
    </div>
  );
}
