import type { Metadata } from 'next';
import './globals.css';
import { LanguageProvider } from '@/components/language-provider';
import { Nav } from '@/components/nav';

export const metadata: Metadata = {
  title: 'SihhatAI — boshqaruv paneli',
  description:
    'Clinical decision support administration for primary care clinics in Uzbekistan.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uz">
      <body>
        <LanguageProvider>
          <Nav />
          <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
        </LanguageProvider>
      </body>
    </html>
  );
}
