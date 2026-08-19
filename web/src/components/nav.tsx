'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLanguage } from './language-provider';
import { t } from '@/lib/i18n';

const links = [
  { href: '/', key: 'nav.dashboard' },
  { href: '/clinics', key: 'nav.clinics' },
  { href: '/audit', key: 'nav.audit' },
] as const;

export function Nav() {
  const pathname = usePathname();
  const { language, setLanguage } = useLanguage();

  return (
    <header className="border-b border-slate-200 dark:border-slate-800">
      <nav className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-4">
        <span className="text-lg font-bold text-brand">SihhatAI</span>
        <div className="flex gap-4">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={
                pathname === link.href
                  ? 'font-semibold text-brand'
                  : 'text-slate-600 hover:text-brand dark:text-slate-400'
              }
            >
              {t(link.key, language)}
            </Link>
          ))}
        </div>
        <div className="ml-auto flex gap-1 rounded-md border border-slate-300 p-0.5 dark:border-slate-700">
          {(['uz', 'ru'] as const).map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => setLanguage(code)}
              className={`rounded px-3 py-1 text-sm ${
                language === code
                  ? 'bg-brand text-white'
                  : 'text-slate-600 dark:text-slate-400'
              }`}
            >
              {code === 'uz' ? "O'zbekcha" : 'Русский'}
            </button>
          ))}
        </div>
      </nav>
    </header>
  );
}
