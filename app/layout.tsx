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
  title: "QueryAssure — Quality Gates for Production Agents",
  description:
    "Test SQL and enterprise agents for unsafe actions, regressions, OAuth scope violations, and missing approvals before merge.",
  icons: {
    icon: `${publicBase}/favicon.svg`,
    shortcut: `${publicBase}/favicon.svg`,
  },
  openGraph: {
    title: "QueryAssure",
    description: "Quality gates for SQL and enterprise agents, including Microsoft 365.",
    type: "website",
    images: [
      {
        url: `${publicBase}/og-v0.5.jpg`,
        width: 1672,
        height: 941,
        alt: "QueryAssure quality gates for SQL and Microsoft 365 agents",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "QueryAssure",
    description: "Quality gates for SQL and enterprise agents, including Microsoft 365.",
    images: [`${publicBase}/og-v0.5.jpg`],
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
