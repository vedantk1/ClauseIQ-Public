"use client";

import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Button from "@/components/Button";
import Card from "@/components/Card";
import { importSource, SourceImportError } from "@/lib/sourceImport";

export default function ImportDocumentPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryId, setRecoveryId] = useState<string | undefined>();
  const importing = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || importing.current) return;
    importing.current = true;
    setPending(true);
    setError(null);
    setRecoveryId(undefined);
    try {
      const source = await importSource(file);
      router.push(`/workspace?documentId=${encodeURIComponent(source.id)}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The import could not be confirmed.");
      if (failure instanceof SourceImportError) setRecoveryId(failure.documentId);
    } finally {
      importing.current = false;
      setPending(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <Link href="/documents" className="text-accent-purple underline">Back to documents</Link>
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Import an agreement</h1>
        <p className="mt-2 text-text-secondary">Save the original and prepare its text locally. No API key or AI call is needed.</p>
      </div>
      <Card className="p-6">
        <form onSubmit={submit} className="space-y-5">
          <div>
            <label htmlFor="source-pdf" className="block font-medium mb-2 text-text-primary">PDF document</label>
            <input id="source-pdf" type="file" accept="application/pdf,.pdf" disabled={pending}
              onChange={(event) => { setFile(event.target.files?.[0] || null); setError(null); setRecoveryId(undefined); }}
              className="block w-full text-text-secondary" />
          </div>
          <p className="text-sm text-text-secondary">Scanned or incomplete text is reported explicitly. Text extraction is not a completed review and does not perform OCR.</p>
          {error && <div role="alert" className="text-status-error space-y-2">
            <p>{error}</p>
            {recoveryId && <Link className="underline" href={`/review?documentId=${encodeURIComponent(recoveryId)}`}>Inspect the saved document record</Link>}
            <p><Link href="/documents" className="underline">Check the library</Link> before importing again if the result is uncertain.</p>
          </div>}
          <Button type="submit" disabled={!file || pending}>{pending ? "Saving original and extracting text..." : "Import without AI"}</Button>
          <p role="status" className="text-sm text-text-tertiary">{pending ? "Wait for confirmation before leaving. Any saved original remains in your library." : "The new workspace is an implementation preview; AI review generation is not connected yet."}</p>
        </form>
      </Card>
      <div className="text-sm text-text-secondary space-y-2">
        <p>For the persistence demonstration, choose the repository’s synthetic <code>tests/fixtures/pdfs/managed-services-25p.pdf</code>. The example findings are available only when the original bytes match.</p>
        <p>Your other PDFs can be imported and given a review brief, but they will not receive invented example findings.</p>
        <Link href="/" className="text-accent-purple underline">Open the existing AI analysis flow instead</Link>
      </div>
    </div>
  );
}
