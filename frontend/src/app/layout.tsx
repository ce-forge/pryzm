import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "DaiNamik Pryzm",
  description: "IT Management Dashboard",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-visual",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="flex h-screen bg-slate-900 text-slate-100 overflow-hidden">
        
        <Suspense fallback={<div className="w-64 bg-slate-950 border-r border-slate-800 p-4">Loading core...</div>}>
        </Suspense>

        <main className="flex-1 flex flex-col h-screen overflow-hidden">
          <Suspense fallback={<div className="flex-1 flex items-center justify-center text-slate-500">Initializing Terminal...</div>}>
            {children}
          </Suspense>
        </main>
        
      </body>
    </html>
  );
}