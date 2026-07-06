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
        <header className="border-b border-midnight-border bg-midnight-card/60 backdrop-blur z-50 relative">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-2 group">
              <span className="text-xl font-bold tracking-widest text-gold uppercase transition-transform group-hover:scale-105">ACN</span>
              <span className="text-sm font-medium tracking-wider text-gray-400">AML Consortium Network</span>
            </Link>
            <nav className="flex items-center gap-6 text-sm">
              <Link href="/" className="text-gray-400 hover:text-mint uppercase tracking-wider font-bold text-xs transition-colors">
                Alert queue
              </Link>
              <span className="text-xs uppercase tracking-wider text-gray-600 font-bold">Unified Compliance</span>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
