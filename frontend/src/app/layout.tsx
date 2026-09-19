import "./globals.css";
import { Inter, Space_Grotesk } from "next/font/google";
import { AppStateProvider } from "@/store/appState";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { AnalysisProvider } from "@/context/AnalysisContext";
import ConditionalNavBar from "@/components/ConditionalNavBar";
import ThemeProvider from "@/components/ThemeProvider";
import ToasterProvider from "@/components/ToasterProvider";
import { ErrorBoundary } from "@/components/ui";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

export const metadata = {
  title: "ClauseIQ - Local Contract Workspace",
  description:
    "Review agreements and ask document-grounded questions in your local workspace.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="black" className="dark" style={{ colorScheme: "dark" }} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} /></head>
      <body
        className={`${inter.variable} ${spaceGrotesk.variable} font-sans bg-bg-primary text-text-primary antialiased`}
      >
        <AppStateProvider>
          <ThemeProvider>
            <WorkspaceProvider>
              <AnalysisProvider>
                <ErrorBoundary>
                  <div className="min-h-screen flex flex-col">
                    <ConditionalNavBar />
                    <main className="flex-1">{children}</main>
                  </div>
                </ErrorBoundary>
                <ToasterProvider />
              </AnalysisProvider>
            </WorkspaceProvider>
          </ThemeProvider>
        </AppStateProvider>
      </body>
    </html>
  );
}
