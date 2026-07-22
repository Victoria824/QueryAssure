import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://dataagentkit-playground.vicalayy.chatgpt.site"),
  title: "QueryAssure — Contract tests and quality gates for SQL Agents",
  description:
    "An open-source SQL Agent playground with contract tests, metadata grounding, validation, benchmarks, and CI quality gates.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "QueryAssure",
    description: "Stop shipping SQL Agents without tests.",
    type: "website",
    images: [{ url: "/og.png", width: 1734, height: 907, alt: "QueryAssure SQL agent trace" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "QueryAssure",
    description: "Stop shipping SQL Agents without tests.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
