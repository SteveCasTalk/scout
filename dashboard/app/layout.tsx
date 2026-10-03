import type { Metadata } from "next";
import { brand } from '@/lib/brand';
import "./globals.css";

export const metadata: Metadata = {
  title: `${brand.name} · Test workspace`,
  description: brand.description,
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
