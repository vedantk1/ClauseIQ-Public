"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import ReviewWorkspace from "@/components/workspace/ReviewWorkspace";

function WorkspacePageContent() {
  const params = useSearchParams();
  const documentId = params.get("documentId");
  if (!documentId) return <div className="mx-auto max-w-xl space-y-3 p-8"><h1 className="text-2xl font-semibold">Choose an agreement</h1><p>Open a stored agreement from your library to start or resume its review workspace.</p><Link className="underline" href="/documents">Open document library</Link></div>;
  return <ReviewWorkspace key={documentId} documentId={documentId} resumeOnOpen={params.get("resume") === "1"} />;
}

export default function WorkspacePage() {
  return <Suspense fallback={<p className="p-8" role="status">Loading workspace…</p>}><WorkspacePageContent /></Suspense>;
}
