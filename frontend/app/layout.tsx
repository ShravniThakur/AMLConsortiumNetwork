import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "ACN — Compliance Console",
  description: "AML Consortium Network — review cross-institution laundering alerts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-lg font-semibold tracking-tight text-white">ACN</span>
              <span className="text-sm text-slate-400">Compliance Console</span>
            </Link>
            <nav className="flex items-center gap-5 text-sm">
              <Link href="/" className="text-slate-300 hover:text-white">
                Alert queue
              </Link>
              <span className="text-xs text-slate-500">AML Consortium Network</span>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
