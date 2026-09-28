import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jev Mobile · Test workspace",
  description: "Test cases, mobile test runs, and evidence in one workspace.",
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
