'use client';

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { Language } from '@/lib/i18n';

interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
}

// Uzbek is the default here as it is everywhere else in the product.
const LanguageContext = createContext<LanguageContextValue>({
  language: 'uz',
  setLanguage: () => undefined,
});

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<Language>('uz');

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    if (typeof document !== 'undefined') {
      document.documentElement.lang = next;
    }
  }, []);

  const value = useMemo(() => ({ language, setLanguage }), [language, setLanguage]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  return useContext(LanguageContext);
}
