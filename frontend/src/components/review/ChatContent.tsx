"use client";

import React from "react";
import DocumentChat from "@/components/DocumentChat";

interface ChatContentProps {
  documentId: string;
}

export default function ChatContent({ documentId }: ChatContentProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0 p-4">
        <DocumentChat documentId={documentId} />
      </div>
    </div>
  );
}
