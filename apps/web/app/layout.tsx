import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Personal Assistant",
  description: "Private modular AI personal operating system",
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
