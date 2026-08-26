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
  title: "Recapp",
  description:
    "Capture meeting decisions and action items locally, with no account and no backend",
};

// Runs before paint so a returning visitor with dark mode saved never sees a
// flash of the light theme first. Can't live in a useEffect: that runs after
// the first paint.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("recapp:theme");
    var dark = stored === "dark" || (!stored && matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      // The theme script below adds the "dark" class before hydration, which
      // will not match what the server rendered. That mismatch is expected
      // and intentional here, so it is suppressed rather than fixed.
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script suppressHydrationWarning dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
