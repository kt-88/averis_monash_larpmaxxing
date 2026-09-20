import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shipping document verification",
  description: "SI vs draft BL checks, from inbox to discrepancy report",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
