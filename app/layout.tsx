import type { Metadata } from "next";
import "./globals.css";

const isGitHubPages = process.env.GITHUB_PAGES === "true";
const publicBase = isGitHubPages ? "/QueryAssure" : "";

export const metadata: Metadata = {
  metadataBase: new URL(
    isGitHubPages
      ? "https://victoria824.github.io"
      : "https://dataagentkit-playground.vicalayy.chatgpt.site",
  ),
  alternates: {
    canonical: `${publicBase}/`,
  },
  title: "QueryAssure — Pytest for SQL Agents",
  description:
    "Catch hallucinated columns, unsafe SQL, semantic regressions, and policy violations before merge.",
  icons: {
    icon: `${publicBase}/favicon.svg`,
    shortcut: `${publicBase}/favicon.svg`,
  },
  openGraph: {
    title: "QueryAssure",
    description: "Pytest for SQL Agents. Catch unsafe SQL and regressions before merge.",
    type: "website",
    images: [{ url: `${publicBase}/og.png`, width: 1672, height: 941, alt: "QueryAssure SQL Agent contract test report" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "QueryAssure",
    description: "Pytest for SQL Agents. Catch unsafe SQL and regressions before merge.",
    images: [`${publicBase}/og.png`],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
