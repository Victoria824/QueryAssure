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
  title: "QueryAssure — Contract tests and quality gates for SQL Agents",
  description:
    "An open-source SQL Agent playground with contract tests, metadata grounding, validation, benchmarks, and CI quality gates.",
  icons: {
    icon: `${publicBase}/favicon.svg`,
    shortcut: `${publicBase}/favicon.svg`,
  },
  openGraph: {
    title: "QueryAssure",
    description: "Stop shipping SQL Agents without tests.",
    type: "website",
    images: [{ url: `${publicBase}/og.png`, width: 1734, height: 907, alt: "QueryAssure SQL agent trace" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "QueryAssure",
    description: "Stop shipping SQL Agents without tests.",
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
