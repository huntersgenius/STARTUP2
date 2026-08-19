interface StatTileProps {
  label: string;
  value: string;
  hint?: string;
  tone?: 'default' | 'ok' | 'warn' | 'danger';
}

const toneClass: Record<NonNullable<StatTileProps['tone']>, string> = {
  default: 'text-slate-900 dark:text-slate-100',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
};

export function StatTile({ label, value, hint, tone = 'default' }: StatTileProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${toneClass[tone]}`}>
        {value}
      </div>
      {hint ? (
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</div>
      ) : null}
    </div>
  );
}
