import "@fontsource-variable/unbounded/index.css";
import "@fontsource/ibm-plex-sans-arabic/arabic-400.css";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "TESSERA · internal research prototype",
  description:
    "A multi-agent research system that compares synthetic offers with UAE regulators' official records.",
  // An internal research tool: nothing here is for search engines.
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="flex min-h-dvh flex-col">
        <div className="aurora" aria-hidden />
        <div className="mosaic-grid" aria-hidden />
        <Shell />
        <main id="main" className="flex flex-1 flex-col pt-4">
          {children}
        </main>
      </body>
    </html>
  );
}
