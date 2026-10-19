import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "GENJUSTSU // 幻術 · Kawarimi Substitution Studio",
  description:
    "GENJUSTSU Kawarimi Substitution Studio. Prepare, review and replace a subject with an OpenArt draft and restore the original audio.",
  icons: { icon: "/ui/favicon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#07070b",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable} antialiased`}>
      <body>{children}</body>
    </html>
  );
}
