import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import Sidebar from "./sidebar";

export const metadata: Metadata = {
  title: "DaiNamik Pryzm",
  description: "IT Management Dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="flex h-screen bg-slate-900 text-slate-100 overflow-hidden">
        
        {/* Next.js requires components reading the URL to be wrapped in Suspense */}
        <Suspense fallback={<div className="w-64 bg-slate-950 border-r border-slate-800 p-4">Loading core...</div>}>
          <Sidebar />
        </Suspense>

        {/* This is where your page.tsx (the Chatbot) renders */}
        <main className="flex-1 flex flex-col h-screen overflow-hidden">
          <Suspense fallback={<div className="flex-1 flex items-center justify-center text-slate-500">Initializing Terminal...</div>}>
            {children}
          </Suspense>
        </main>
        
      </body>
    </html>
  );
}