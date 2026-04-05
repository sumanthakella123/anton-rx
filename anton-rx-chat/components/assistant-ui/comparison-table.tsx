"use client";

import React, { useState } from "react";
import { Loader2, Download, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

function escapeCell(value: unknown): string {
  const str = value == null ? "" : String(value);
  // Wrap in quotes if the cell contains commas, newlines, or quotes
  if (str.includes(",") || str.includes("\n") || str.includes('"')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function buildCsv(drugName: string, comparison: any[]): string {
  const rows: string[][] = [
    ["Attribute", ...comparison.map((c) => c.payer)],
    ["Effective Date", ...comparison.map((c) => c.effective_date ?? "Unknown")],
    ["Drug (Brand)", ...comparison.map((c) => c.brand_name ?? "")],
    ["Drug (Generic)", ...comparison.map((c) => c.generic_name ?? "")],
    ["Coverage Status", ...comparison.map((c) => c.coverage_status ?? "")],
    ["Prior Auth Required", ...comparison.map((c) => c.prior_auth_required ?? "")],
    ["Step Therapy", ...comparison.map((c) => c.step_therapy_required ?? "N/A")],
    ["Clinical Criteria (PA)", ...comparison.map((c) => c.prior_auth_criteria ?? "")],
  ];
  return `Drug: ${drugName}\n` + rows.map((r) => r.map(escapeCell).join(",")).join("\n");
}

export const ComparisonTableTool = (part: any) => {
  const { args, result, status } = part;
  const [copied, setCopied] = useState(false);

  const drugName = args?.query || args?.drug_name || "drug";

  if (!result || (status && status.type === "running")) {
    return (
      <div className="w-full my-4 rounded-xl border bg-muted/50 text-card-foreground shadow-sm">
        <div className="flex items-center gap-3 p-6 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Generating side-by-side comparison for {drugName} across payers...</span>
        </div>
      </div>
    );
  }

  if (!result.success || !result.comparison || result.comparison.length === 0) {
    return (
      <div className="w-full my-4 rounded-xl border border-destructive/50 bg-card text-card-foreground shadow-sm">
        <div className="p-6 py-4">
          <p className="text-destructive font-medium">
            {result.message || "Failed to compare policies or no data found."}
          </p>
        </div>
      </div>
    );
  }

  const comparison: any[] = result.comparison;

  const handleExport = () => {
    const csv = buildCsv(drugName, comparison);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${drugName.replace(/\s+/g, "_")}_payer_comparison.csv`;
    a.click();
    URL.revokeObjectURL(url);

    // Also copy to clipboard for easy paste into reports
    navigator.clipboard.writeText(csv).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full my-4 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-start justify-between gap-4 p-6 bg-muted/30 pb-4">
        <div className="flex flex-col space-y-1.5">
          <h3 className="font-semibold leading-none tracking-tight text-lg text-primary">
            Comparison: {drugName}
          </h3>
          <p className="text-sm text-muted-foreground">
            Contrasting medical benefit policies across {comparison.map((p) => p.payer).join(", ")}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0 gap-1.5"
          onClick={handleExport}
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-emerald-600" />
              <span className="text-emerald-600">Downloaded</span>
            </>
          ) : (
            <>
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </>
          )}
        </Button>
      </div>
      <div className="overflow-x-auto w-full p-0">
        <table className="w-full caption-bottom text-sm table-fixed min-w-[600px]">
          <thead className="[&_tr]:border-b">
            <tr className="border-b transition-colors bg-muted/50 hover:bg-muted/50">
              <th className="h-12 px-4 text-left align-middle font-semibold w-48 text-muted-foreground">
                Attribute
              </th>
              {comparison.map((col, idx) => (
                <th key={idx} className="h-12 px-4 text-left align-middle font-bold text-foreground">
                  {col.payer}
                  <div className="text-xs font-normal text-muted-foreground mt-1">
                    Effective: {col.effective_date || "Unknown"}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="[&_tr:last-child]:border-0">
            <tr className="border-b transition-colors hover:bg-muted/50">
              <td className="p-4 align-top font-semibold bg-muted/20 border-r">Coverage Status</td>
              {comparison.map((col, idx) => (
                <td key={idx} className="p-4 align-top border-r last:border-r-0">
                  <span
                    className={
                      col.coverage_status?.toLowerCase().includes("not covered")
                        ? "text-destructive font-medium"
                        : "text-emerald-600 font-medium"
                    }
                  >
                    {col.coverage_status}
                  </span>
                </td>
              ))}
            </tr>
            <tr className="border-b transition-colors hover:bg-muted/50">
              <td className="p-4 align-top font-semibold bg-muted/20 border-r">Prior Auth Required</td>
              {comparison.map((col, idx) => (
                <td key={idx} className="p-4 align-top border-r last:border-r-0 whitespace-pre-wrap">
                  {col.prior_auth_required}
                </td>
              ))}
            </tr>
            <tr className="border-b transition-colors hover:bg-muted/50">
              <td className="p-4 align-top font-semibold bg-muted/20 border-r">Step Therapy</td>
              {comparison.map((col, idx) => (
                <td key={idx} className="p-4 align-top border-r last:border-r-0 whitespace-pre-wrap">
                  {col.step_therapy_required || "N/A"}
                </td>
              ))}
            </tr>
            <tr className="border-b transition-colors hover:bg-transparent">
              <td className="p-4 align-top font-semibold bg-muted/20 border-r py-4">
                Clinical Criteria (PA)
              </td>
              {comparison.map((col, idx) => (
                <td key={idx} className="p-4 align-top border-r last:border-r-0 py-4">
                  <div className="text-sm prose prose-sm dark:prose-invert max-w-none max-h-[300px] overflow-y-auto pr-2">
                    {col.prior_auth_criteria ? (
                      col.prior_auth_criteria
                        .split("\n")
                        .map((line: string, i: number) => (
                          <p key={i} className="mb-2 leading-relaxed">
                            {line}
                          </p>
                        ))
                    ) : (
                      <span className="text-muted-foreground italic">None listed</span>
                    )}
                  </div>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};
