import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sieve — Recruitment Agent",
  description: "AI-powered resume screening and interview agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
