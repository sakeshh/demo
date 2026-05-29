'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaTags, FaArrowLeft, FaCheck, FaExclamationTriangle, FaSpinner, FaEdit, FaMagic } from 'react-icons/fa';
import SemanticColumnEditor from '@/components/SemanticColumnEditor';
import { DQGateResult } from '@/types/pipeline';

interface SemanticReviewPanelProps {
  database: string;
  files: string[];
  assessment: any;
  dqGate: DQGateResult | null;
  onComplete: (approvedSemantics: Record<string, any>) => void;
  onBack: () => void;
}

type ColumnSemantics = {
  name: string;
  semantic_type: string;
  sub_type: string;
  pii_level: 'none' | 'low' | 'medium' | 'high';
  confidence: number;
  inferred_by: string;
  samples: string[];
};

type TableSemanticsMap = Record<string, ColumnSemantics[]>;

export default function SemanticReviewPanel({
  database,
  files,
  assessment,
  dqGate,
  onComplete,
  onBack,
}: SemanticReviewPanelProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [semanticsMap, setSemanticsMap] = useState<TableSemanticsMap>({});
  const [editingCol, setEditingCol] = useState<{ table: string; col: string } | null>(null);
  const [enriching, setEnriching] = useState(false);

  useEffect(() => {
    if (assessment && assessment.datasets) {
      const tableMap: TableSemanticsMap = {};
      Object.entries(assessment.datasets).forEach(([tableName, dsMeta]: [string, any]) => {
        if (files.includes(tableName)) {
          const cols = dsMeta.columns || {};
          tableMap[tableName] = Object.entries(cols).map(([colName, colMeta]: [string, any]) => {
            return {
              name: colName,
              semantic_type: colMeta.semantic_type || 'string',
              sub_type: colMeta.sub_type || 'unknown',
              pii_level: colMeta.pii_level || 'none',
              confidence: colMeta.confidence != null ? colMeta.confidence : 0.6,
              inferred_by: colMeta.inferred_by || 'heuristic',
              samples: colMeta.raw_samples || [],
            };
          });
        }
      });
      setSemanticsMap(tableMap);
      setLoading(false);
    } else {
      setLoading(false);
      setError('No assessment data available to review column semantics.');
    }
  }, [assessment, files]);

  const handleEditSave = (
    tableName: string,
    colName: string,
    updates: { semantic_type: string; sub_type: string; pii_level: 'none' | 'low' | 'medium' | 'high' }
  ) => {
    setSemanticsMap((prev) => {
      const updated = { ...prev };
      updated[tableName] = updated[tableName].map((col) =>
        col.name === colName
          ? {
              ...col,
              ...updates,
              confidence: 1.0,
              inferred_by: 'user_override',
            }
          : col
      );
      return updated;
    });
    setEditingCol(null);
  };

  const runLlmEnrichment = async () => {
    setEnriching(true);
    setError(null);
    try {
      // Gather all low-confidence columns (< 0.75) across tables
      const lowConfBatch: Record<string, any> = {};
      Object.entries(semanticsMap).forEach(([tableName, columns]) => {
        columns.forEach((col) => {
          if (col.confidence < 0.75) {
            const key = `${tableName}.${col.name}`;
            const colMeta = assessment?.datasets?.[tableName]?.columns?.[col.name] || {};
            lowConfBatch[key] = {
              col_name: col.name,
              col_meta: {
                ...colMeta,
                raw_samples: col.samples,
              },
              descriptor: {
                semantic_type: col.semantic_type,
                sub_type: col.sub_type,
                pii_level: col.pii_level,
                confidence: col.confidence,
              },
            };
          }
        });
      });

      if (Object.keys(lowConfBatch).length === 0) {
        alert('All columns are already classified with high confidence!');
        setEnriching(false);
        return;
      }

      const res = await fetch('/api/etl/enrich-semantics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ low_confidence_cols: lowConfBatch }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        throw new Error(data?.message || 'Inference enrichment failed');
      }

      // Merge enriched values back
      setSemanticsMap((prev) => {
        const updated = { ...prev };
        Object.entries(updated).forEach(([tableName, columns]) => {
          updated[tableName] = columns.map((col) => {
            const key = `${tableName}.${col.name}`;
            const enrichedDesc = data.enriched?.[key];
            if (enrichedDesc) {
              return {
                ...col,
                semantic_type: enrichedDesc.semantic_type,
                sub_type: enrichedDesc.sub_type,
                pii_level: enrichedDesc.pii_level,
                confidence: enrichedDesc.confidence || 0.95,
                inferred_by: enrichedDesc.inferred_by || 'llm',
              };
            }
            return col;
          });
        });
        return updated;
      });
    } catch (err: any) {
      setError(err.message || 'Failed to enrich semantics using LLM.');
    } finally {
      setEnriching(false);
    }
  };

  const handleConfirm = () => {
    const overrides: Record<string, any> = {};
    Object.entries(semanticsMap).forEach(([tableName, columns]) => {
      columns.forEach((col) => {
        const key = `${tableName}.${col.name}`;
        overrides[key] = {
          semantic_type: col.semantic_type,
          sub_type: col.sub_type,
          pii_level: col.pii_level,
        };
      });
    });
    onComplete(overrides);
  };

  // Find count of columns under 75% confidence
  const lowConfidenceCount = Object.values(semanticsMap).reduce(
    (acc, cols) => acc + cols.filter((c) => c.confidence < 0.75).length,
    0
  );

  if (loading || enriching) {
    return (
      <div className="flex flex-col items-center justify-center space-y-8 py-16">
        <div className="relative">
          <div className="absolute inset-0 scale-150 blur-3xl bg-gradient-to-tr from-[#0070AD]/20 to-[#12ABDB]/20 animate-pulse" />
          <div className="relative flex h-24 w-24 items-center justify-center rounded-3xl bg-white shadow-2xl">
            <FaSpinner className="h-12 w-12 animate-spin text-[#0070AD]" />
          </div>
        </div>
        <div className="text-center space-y-2">
          <h3 className="text-2xl font-bold text-zinc-900">
            {enriching ? 'Enriching with Semantics LLM' : 'Loading Assessment Semantics'}
          </h3>
          <p className="text-sm text-black/50">
            {enriching
              ? 'Analyzing low-confidence columns with OpenAI...'
              : 'Pulling parsed heuristics from report...'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-zinc-900 mb-2 flex items-center gap-2">
            <FaTags className="text-[#0070AD]" />
            Verify Column Semantics
          </h2>
          <p className="text-black/60">
            Review column types, check PII levels, and trigger LLM enrichment to refine classifications.
          </p>
        </div>
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm text-black/65 hover:text-black transition-colors"
        >
          <FaArrowLeft />
          <span>Back</span>
        </button>
      </div>

      {lowConfidenceCount > 0 && (
        <div className="flex items-center justify-between p-4 rounded-xl border border-amber-500/10 bg-amber-500/5">
          <div className="flex items-center gap-2.5 text-xs text-amber-800 font-semibold">
            <FaExclamationTriangle className="text-amber-600 text-sm flex-shrink-0" />
            <span>
              {lowConfidenceCount} column(s) below 75% confidence — LLM enrichment is recommended.
            </span>
          </div>
          <button
            onClick={runLlmEnrichment}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-xs font-bold text-white shadow-sm transition-colors"
          >
            <FaMagic />
            <span>Run LLM Enrichment</span>
          </button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/10 bg-rose-500/5 text-xs text-rose-700 font-medium">
          ⚠️ {error}
        </div>
      )}

      <div className="space-y-8 max-h-[calc(100vh-340px)] overflow-y-auto pr-2">
        {Object.entries(semanticsMap).map(([tableName, columns]) => {
          const dsScore = dqGate?.datasets?.[tableName]?.dq_score ?? 100;
          return (
            <motion.div
              key={tableName}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-black/10 bg-white/60 p-6 shadow-sm"
            >
              <h3 className="text-md font-bold text-zinc-900 mb-4 pb-2 border-b border-black/5 flex items-center justify-between">
                <span>
                  Table: <span className="text-[#0070AD]">{tableName}</span>
                </span>
                <span className="text-xs text-black/50">DQ Score: {dsScore}%</span>
              </h3>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] font-bold uppercase tracking-wider text-black/40 border-b border-black/5 font-sans">
                      <th className="py-3 text-left">Column</th>
                      <th className="py-3 text-left">Category / Sub-type</th>
                      <th className="py-3 text-left">PII Level</th>
                      <th className="py-3 text-left">Confidence</th>
                      <th className="py-3 text-left">Sample Values</th>
                      <th className="py-3 w-20 text-center">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/5">
                    {columns.map((col) => {
                      const isEditing = editingCol?.table === tableName && editingCol?.col === col.name;
                      const hasLowConfidence = col.confidence < 0.75;
                      return (
                        <tr key={col.name} className="hover:bg-black/[0.005]">
                          <td className="py-3 font-semibold text-zinc-800">{col.name}</td>
                          <td className="py-3 font-medium capitalize text-zinc-600">
                            {col.semantic_type} ({col.sub_type})
                          </td>
                          <td className="py-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide border ${
                                col.pii_level === 'high'
                                  ? 'bg-rose-500/10 border-rose-500/20 text-rose-600'
                                  : col.pii_level === 'medium'
                                    ? 'bg-amber-500/10 border-amber-500/20 text-amber-600'
                                    : col.pii_level === 'low'
                                      ? 'bg-blue-500/10 border-blue-500/20 text-blue-600'
                                      : 'bg-zinc-100 border-zinc-200 text-zinc-600'
                              }`}
                            >
                              {col.pii_level}
                            </span>
                          </td>
                          <td className="py-3">
                            <span
                              className={`font-semibold ${
                                hasLowConfidence ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold'
                              }`}
                            >
                              {Math.round(col.confidence * 100)}%
                            </span>
                            <span className="text-[10px] text-black/35 block font-medium capitalize">
                              Inferred: {col.inferred_by}
                            </span>
                          </td>
                          <td className="py-3 max-w-[200px] truncate">
                            <div className="flex flex-wrap gap-1">
                              {col.samples.length > 0 ? (
                                col.samples.slice(0, 3).map((val, idx) => (
                                  <span
                                    key={idx}
                                    className="bg-black/5 px-2 py-0.5 rounded text-[10px] text-black/60 font-mono truncate"
                                    title={val}
                                  >
                                    {val}
                                  </span>
                                ))
                              ) : (
                                <span className="text-black/35 italic">No samples</span>
                              )}
                            </div>
                          </td>
                          <td className="py-2 text-center">
                            <button
                              type="button"
                              onClick={() => setEditingCol({ table: tableName, col: col.name })}
                              className="p-2 rounded hover:bg-black/5 text-[#0070AD] hover:text-[#0070AD]/90 flex items-center justify-center gap-1 font-bold text-xs mx-auto"
                            >
                              <FaEdit />
                              <span>Edit</span>
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {editingCol?.table === tableName && (
                <AnimatePresence>
                  {columns
                    .filter((c) => c.name === editingCol.col)
                    .map((col) => (
                      <SemanticColumnEditor
                        key={col.name}
                        columnName={col.name}
                        currentType={col.semantic_type}
                        currentSubType={col.sub_type}
                        currentPii={col.pii_level}
                        onSave={(updates) => handleEditSave(tableName, col.name, updates)}
                        onCancel={() => setEditingCol(null)}
                      />
                    ))}
                </AnimatePresence>
              )}
            </motion.div>
          );
        })}
      </div>

      <motion.button
        onClick={handleConfirm}
        className="w-full py-4 rounded-xl border border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] font-semibold hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60 transition-all flex items-center justify-center gap-2"
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.99 }}
      >
        <FaCheck />
        <span>Confirm Semantics & Continue to Requirements</span>
      </motion.button>
    </div>
  );
}
