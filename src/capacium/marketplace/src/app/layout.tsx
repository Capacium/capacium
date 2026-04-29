import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";

export const metadata: Metadata = {
  title: "Capacium Marketplace — AI Agent Capabilities",
  description: "Discover, install, and share AI agent capabilities",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg-primary text-text-primary">
        <Header />
        {children}
      </body>
    </html>
  );
}
