import "./globals.css";
import type { Metadata } from "next";
import Sidebar from "./components/Sidebar";
import ContentWrapper from "./components/ContentWrapper";

export const metadata: Metadata = {
  title: "ACN — Compliance Console",
  description: "AML Consortium Network — review cross-institution laundering alerts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="min-h-screen" style={{ background: "#f0efeb" }}>
        {/* Sidebar — self-hides on auth routes */}
        <Sidebar />
        {/* Content — offset only on dashboard routes */}
        <ContentWrapper>{children}</ContentWrapper>
      </body>
    </html>
  );
}
