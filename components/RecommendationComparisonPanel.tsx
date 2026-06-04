'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { FaRobot, FaFolderOpen, FaCopy, FaCheck } from 'react-icons/fa';
import { ManualReviewItem, ResolutionOption } from './ManualReviewPanel';

interface RecommendationComparisonPanelProps {
  item: ManualReviewItem;
  selectedId: string;
  onSelect: (resolutionId: string) => void;
  darkMode?: boolean;
}

export default function RecommendationComparisonPanel({
  item,
  selectedId,
  onSelect,
  darkMode = false,
}: RecommendationComparisonPanelProps) {
  const [copiedSql, setCopiedSql] = useState(false);
  const [copiedPandas, setCopiedPandas] = useState(false);

  const llmRec = item.llm_recommendation;
  const options = item.resolution_options || [];

  // Split options into AI-suggested and catalog ones
  const aiOption = options.find((o) => o.id === 'llm_suggested');
  const catalogOptions = options.filter((o) => o.id !== 'llm_suggested');

  const handleCopy = (text: string, type: 'sql' | 'pandas') => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      if (type === 'sql') {
        setCopiedSql(true);
        setTimeout(() => setCopiedSql(false), 2000);
      } else {
        setCopiedPandas(true);
        setTimeout(() => setCopiedPandas(false), 2000);
      }
    }
  };

  const confidence = aiOption?.llm_metadata?.confidence ?? 0.8;
  const confidencePct = Math.round(confidence * 100);

  const sub = darkMode ? 'text-zinc-400' : 'text-black/60';
  const text = darkMode ? 'text-zinc-100' : 'text-zinc-900';

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-3">
      {/* AI Recommendation Panel */}
      {llmRec && aiOption && (
        <div className={`rounded-xl border p-4 transition-all flex flex-col justify-between ${
          selectedId === 'llm_suggested'
            ? 'border-purple-400 bg-purple-500/10 ring-1 ring-purple-400'
            : darkMode
              ? 'border-white/10 bg-white/5 hover:border-purple-400/50'
              : 'border-black/5 bg-black/[0.01] hover:border-purple-300'
        }`}>
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="flex items-center gap-1.5 text-xs font-black text-purple-600 uppercase tracking-wider">
                <FaRobot /> AI Recommendation
              </span>
              <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${
                confidence >= 0.8 ? 'bg-emerald-500/15 text-emerald-600' : 'bg-amber-500/15 text-amber-600'
              }`}>
                {confidencePct}% Confidence
              </span>
            </div>

            <h4 className={`text-xs font-bold mb-1.5 ${text}`}>
              Suggested Fix: <span className="font-normal opacity-90">{llmRec.suggested_fix}</span>
            </h4>
            <p className={`text-[11px] mb-2 leading-relaxed ${sub}`}>
              <strong>Why it matters:</strong> {llmRec.why_it_matters}
            </p>
            <p className={`text-[11px] mb-3 leading-relaxed text-red-500`}>
              <strong>Risk:</strong> ⚠️ {llmRec.risk}
            </p>

            {/* Code snippets */}
            {(llmRec.example_sql || llmRec.example_pandas) && (
              <div className="space-y-2 mt-3 mb-4">
                {llmRec.example_sql && (
                  <div className="rounded border border-black/10 bg-black/5 p-2 text-[10px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold opacity-60">SQL Fix Suggestion</span>
                      <button
                        onClick={() => handleCopy(llmRec.example_sql, 'sql')}
                        className="p-1 hover:bg-black/10 rounded transition text-purple-600"
                        title="Copy SQL snippet"
                      >
                        {copiedSql ? <FaCheck /> : <FaCopy />}
                      </button>
                    </div>
                    <pre className="font-mono overflow-x-auto max-h-24 whitespace-pre">{llmRec.example_sql}</pre>
                  </div>
                )}
                {llmRec.example_pandas && (
                  <div className="rounded border border-black/10 bg-black/5 p-2 text-[10px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold opacity-60">Pandas Fix Suggestion</span>
                      <button
                        onClick={() => handleCopy(llmRec.example_pandas, 'pandas')}
                        className="p-1 hover:bg-black/10 rounded transition text-purple-600"
                        title="Copy Pandas snippet"
                      >
                        {copiedPandas ? <FaCheck /> : <FaCopy />}
                      </button>
                    </div>
                    <pre className="font-mono overflow-x-auto max-h-24 whitespace-pre">{llmRec.example_pandas}</pre>
                  </div>
                )}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => onSelect('llm_suggested')}
            className={`w-full py-2 rounded-lg text-xs font-bold transition-all mt-2 ${
              selectedId === 'llm_suggested'
                ? 'bg-purple-600 text-white shadow-md'
                : 'border border-purple-500/30 text-purple-600 hover:bg-purple-500/5'
            }`}
          >
            {selectedId === 'llm_suggested' ? '✨ Selected AI Action' : 'Use AI Recommendation'}
          </button>
        </div>
      )}

      {/* Catalog Options Panel */}
      <div className={`rounded-xl border p-4 transition-all flex flex-col justify-between ${
        selectedId !== 'llm_suggested'
          ? 'border-emerald-400 bg-emerald-500/5 ring-1 ring-emerald-400'
          : darkMode
            ? 'border-white/10 bg-white/5 hover:border-emerald-400/50'
            : 'border-black/5 bg-black/[0.01] hover:border-emerald-300'
      }`}>
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="flex items-center gap-1.5 text-xs font-black text-emerald-600 uppercase tracking-wider">
              <FaFolderOpen /> Standard Catalog Options
            </span>
            <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-zinc-500/10 text-zinc-500">
              Pre-defined rules
            </span>
          </div>

          <div className="space-y-2">
            {catalogOptions.map((opt) => {
              const active = selectedId === opt.id;
              return (
                <div
                  key={opt.id}
                  onClick={() => onSelect(opt.id)}
                  className={`cursor-pointer rounded-lg border p-2 text-[11px] transition-all ${
                    active
                      ? 'border-emerald-500 bg-emerald-500/10 shadow-sm'
                      : darkMode
                        ? 'border-white/5 hover:bg-white/5'
                        : 'border-black/5 hover:bg-black/[0.02]'
                  }`}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className={`font-semibold ${text}`}>{opt.label}</span>
                    {opt.recommended && (
                      <span className="text-[9px] font-black text-emerald-600 uppercase">Default Recommended</span>
                    )}
                  </div>
                  {opt.description && <p className={`leading-normal ${sub}`}>{opt.description}</p>}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-4">
          <div className={`text-[10px] text-center mb-2 ${sub}`}>
            {selectedId !== 'llm_suggested' ? (
              <span>Active Selection: <strong>{options.find((o) => o.id === selectedId)?.label || 'None'}</strong></span>
            ) : (
              <span>Catalog option is currently inactive</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
