"use client";

import { Download } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { saveJson } from "@/lib/download";

/** The only export: the event log, masked as stored. A report is never written to a file. */
export function TraceButton({ id, label }: { id: string; label: string }) {
  const [failed, setFailed] = useState(false);
  const save = async () => {
    try {
      saveJson(`${id}-trace.json`, await api.trace(id));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  };
  return (
    <>
      {failed && (
        <span className="text-sm text-challenge" role="alert">
          The trace could not be fetched.
        </span>
      )}
      <button
        type="button"
        className="button h-9!"
        onClick={() => void save()}
        title="The event log, masked as stored. The report itself is not exported."
      >
        <Download size={15} aria-hidden /> {label}
      </button>
    </>
  );
}
