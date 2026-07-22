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
  title: "DataAgentKit — Test data agents before they test production",
  description:
    "An open-source SQL agent playground and CI quality gate for agentic analytics.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "DataAgentKit",
    description: "Test data agents before they test production.",
    type: "website",
    images: [{ url: "/og.png", width: 1734, height: 907, alt: "DataAgentKit SQL agent trace" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "DataAgentKit",
    description: "Test data agents before they test production.",
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
