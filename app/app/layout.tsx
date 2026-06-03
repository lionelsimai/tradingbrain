import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradingBrain",
  description: "Paper trading dashboard for TradingBrain recommendations",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
