'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { FaBug, FaClipboard, FaCode, FaDatabase, FaExclamationTriangle, FaInfoCircle, FaWrench } from 'react-icons/fa';

type Severity = 'high' | 'medium' | 'low';

function normSeverity(s: any): Severity {
  const t = String(s || '').toLowerCase();
  if (t === 'high') return 'high';
  if (t === 'medium') return 'medium';
  return 'low';
}

function severityStyles(sev: Severity): string {
  if (sev === 'high') return 'bg-red-500/15 text-red-700 border-red-500/30';
  if (sev === 'medium') return 'bg-amber-500/15 text-amber-700 border-amber-500/30';
  return 'bg-blue-500/15 text-blue-700 border-blue-500/30';
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // ignore
  }
}

type Props = {
  result: any;
  userIntent?: string;
  enableTransformSuggestions?: boolean;
  enableDqRecommendations?: boolean;
  variant?: 'chat' | 'pipeline';
  gxEnabled?: boolean;
};

export default function ReportEnhancements({
  result,
  userIntent = '',
  enableTransformSuggestions = true,
  enableDqRecommendations = true,
  variant = 'chat',
  gxEnabled = false,
}: Props) {
  const [dqRecLoading, setDqRecLoading] = useState(false);
  const [dqRec, setDqRec] = useState<any>(null);
  const [dqRecErr, setDqRecErr] = useState<string | null>(null);

  const [tfLoading, setTfLoading] = useState(false);
  const [tf, setTf] = useState<any>(null);
  const [tfErr, setTfErr] = useState<string | null>(null);

  const dqPayload = result?.data_quality ?? result?.data_quality_issues ?? null;
  const timings = result?.timings && typeof result.timings === "object" ? result.timings : null;
  const requestId = typeof result?.request_id === 'string' ? result.request_id : '';
  const extractionErrors = Array.isArray(result?.extraction_errors) ? result.extraction_errors : null;

  useEffect(() => {
    let alive = true;
    (async () => {
      // DQ recommendations
      if (!enableDqRecommendations) return;
      if (result?.dq_recommendations) {
        if (alive) setDqRec(result.dq_recommendations);
        return;
      }
      if (!dqPayload || typeof dqPayload !== 'object') return;
      setDqRecLoading(true);
      setDqRecErr(null);
      try {
        const res = await fetch('/api/dq-recommend', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data_quality: dqPayload, user_intent: userIntent }),
        });
        const j = await res.json().catch(() => null);
        if (!alive) return;
        if (!res.ok) throw new Error(j?.detail || 'Failed to generate recommendations');
        setDqRec(j?.recommendations ?? null);
      } catch (e: any) {
        if (!alive) return;
        setDqRecErr(e?.message || 'Failed to generate recommendations');
      } finally {
        if (alive) setDqRecLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enableDqRecommendations, JSON.stringify(Boolean(result?.dq_recommendations)), JSON.stringify(Boolean(dqPayload))]);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!enableTransformSuggestions) return;
      if (result?.transform_suggestions) {
        if (alive) setTf(result.transform_suggestions);
        return;
      }
      setTfLoading(true);
      setTfErr(null);
      try {
        const res = await fetch('/api/transform-suggest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assessment_result: result }),
        });
        const j = await res.json().catch(() => null);
        if (!alive) return;
        if (!res.ok) throw new Error(j?.detail || 'Failed to generate transform suggestions');
        setTf(j?.suggestions ?? null);
      } catch (e: any) {
        if (!alive) return;
        setTfErr(e?.message || 'Failed to generate transform suggestions');
      } finally {
        if (alive) setTfLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [enableTransformSuggestions, result]);

  const recList: any[] = useMemo(() => {
    const r = dqRec?.recommendations;
    if (!Array.isArray(r)) return [];
    return [...r]
      .filter((x) => x && typeof x === 'object')
      .sort((a, b) => Number(a?.priority ?? 999) - Number(b?.priority ?? 999))
      .sort((a, b) => Number(a?.priority ?? 999) - Number(b?.priority ?? 999));
  }, [dqRec]);

  const tfByAction = useMemo(() => {
    const src = tf?.sources;
    const out: Record<string, { action: string; count: number; items: any[] }> = {};
    const blocks: any[] = [];
    if (src && typeof src === 'object') {
      for (const [k, v] of Object.entries(src)) blocks.push({ source: k, val: v });
    } else {
      blocks.push({ source: 'result', val: tf });
    }
    for (const b of blocks) {
      const items = Array.isArray((b.val as any)?.suggested_transformations) ? (b.val as any).suggested_transformations : [];
      for (const it of items) {
        const action = String(it?.suggested_action || 'review_manually');
        if (!out[action]) out[action] = { action, count: 0, items: [] };
        out[action].count += 1;
        out[action].items.push({ ...it, _source: b.source });
      }
    }
    return Object.values(out).sort((a, b) => b.count - a.count);
  }, [tf]);

  const showDiagnostics = Boolean(requestId || timings || (extractionErrors && extractionErrors.length));

  return (
    <div className="space-y-4">
      {/* Cleaning recommendations */}
      {enableDqRecommendations ? (
        <div className={`rounded-2xl border p-6 shadow-2xl backdrop-blur-md transition-all duration-500 ${
          gxEnabled ? 'border-emerald-500/20 bg-[#000B14]/80' : 'border-[#0070AD]/30 bg-white/60 shadow-[0_8px_32px_rgba(0,0,0,0.08)]'
        }`}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className={`flex h-12 w-12 items-center justify-center rounded-2xl shadow-lg ${
                gxEnabled ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-black shadow-emerald-500/20' : 'bg-gradient-to-br from-[#0070AD] to-[#12ABDB] text-white shadow-[#0070AD]/20'
              }`}>
                <FaWrench className="text-xl" />
              </div>
              <div>
                <h3 className={`text-lg font-black tracking-tight ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>Cleaning Recommendations</h3>
                <p className={`text-[12.5px] font-medium ${gxEnabled ? 'text-emerald-400/60' : 'text-black/50'}`}>Prioritized actions to improve data quality</p>
              </div>
            </div>
            {variant === 'pipeline' && (
              <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-bold ${
                gxEnabled ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400' : 'border-[#0070AD]/20 bg-[#0070AD]/5 text-[#0070AD]'
              }`}>
                <FaInfoCircle className="animate-pulse" />
                <span>AI-Assisted Assessment</span>
              </div>
            )}
          </div>

          {dqRecLoading ? (
            <div className="mt-8 flex flex-col items-center justify-center gap-3 py-12 text-center">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#0070AD]/10 border-t-[#0070AD]" />
              <p className="text-sm font-bold text-[#0070AD] animate-pulse">Analyzing issues & generating fixes...</p>
            </div>
          ) : dqRecErr ? (
            <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-center">
              <p className="text-sm font-bold text-red-700">{dqRecErr}</p>
            </div>
          ) : recList.length === 0 ? (
            <div className="mt-8 rounded-2xl border border-dashed border-[#0070AD]/20 py-12 text-center">
              <p className="text-sm font-bold text-black/40">No recommendations available for this dataset.</p>
            </div>
          ) : (
            <div className="mt-8 space-y-4">
              {/* Summary Stats for Recommendations */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className={`rounded-xl border p-3 text-center transition-colors ${
                  gxEnabled ? 'border-emerald-500/10 bg-white/5' : 'border-[#0070AD]/10 bg-white/40'
                }`}>
                  <div className={`text-[10px] font-black uppercase tracking-widest ${gxEnabled ? 'text-white/40' : 'text-black/40'}`}>Total Fixes</div>
                  <div className={`text-xl font-black ${gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]'}`}>{recList.length}</div>
                </div>
                <div className={`rounded-xl border p-3 text-center transition-colors ${
                  gxEnabled ? 'border-red-500/20 bg-red-500/5' : 'border-red-500/10 bg-red-50/30'
                }`}>
                  <div className={`text-[10px] font-black uppercase tracking-widest ${gxEnabled ? 'text-red-400/60' : 'text-red-500/60'}`}>High Priority</div>
                  <div className={`text-xl font-black ${gxEnabled ? 'text-red-400' : 'text-red-600'}`}>{recList.filter(r => normSeverity(r?.severity) === 'high').length}</div>
                </div>
                <div className={`rounded-xl border p-3 text-center transition-colors ${
                  gxEnabled ? 'border-amber-500/20 bg-amber-500/5' : 'border-amber-500/10 bg-amber-50/30'
                }`}>
                  <div className={`text-[10px] font-black uppercase tracking-widest ${gxEnabled ? 'text-amber-400/60' : 'text-amber-500/60'}`}>Medium</div>
                  <div className={`text-xl font-black ${gxEnabled ? 'text-amber-400' : 'text-amber-600'}`}>{recList.filter(r => normSeverity(r?.severity) === 'medium').length}</div>
                </div>
                <div className={`rounded-xl border p-3 text-center transition-colors ${
                  gxEnabled ? 'border-blue-500/20 bg-blue-500/5' : 'border-blue-500/10 bg-blue-50/30'
                }`}>
                  <div className={`text-[10px] font-black uppercase tracking-widest ${gxEnabled ? 'text-blue-400/60' : 'text-blue-500/60'}`}>Low</div>
                  <div className={`text-xl font-black ${gxEnabled ? 'text-blue-400' : 'text-blue-600'}`}>{recList.filter(r => normSeverity(r?.severity) === 'low').length}</div>
                </div>
              </div>

              {recList.map((r, idx) => {
                const sev = normSeverity(r?.severity);
                return (
                  <motion.div 
                    key={idx} 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className={`group relative overflow-hidden rounded-2xl border p-5 shadow-sm transition-all hover:shadow-md ${
                      gxEnabled ? 'border-white/10 bg-white/5 hover:border-emerald-500/40 hover:bg-white/10' : 'border-black/10 bg-white/70 hover:border-[#0070AD]/40'
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="flex items-start gap-4">
                        <div className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg font-black text-sm shadow-sm ${
                          sev === 'high' ? 'bg-red-600 text-white' : 
                          sev === 'medium' ? 'bg-amber-500 text-white' : 
                          gxEnabled ? 'bg-emerald-600 text-black' : 'bg-blue-600 text-white'
                        }`}>
                          {idx + 1}
                        </div>
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider shadow-sm ${
                              sev === 'high' ? (gxEnabled ? 'bg-red-500/20 text-red-400 border-red-500/40' : 'bg-red-500/15 text-red-700 border-red-500/30') :
                              sev === 'medium' ? (gxEnabled ? 'bg-amber-500/20 text-amber-400 border-amber-500/40' : 'bg-amber-500/15 text-amber-700 border-amber-500/30') :
                              (gxEnabled ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40' : 'bg-blue-500/15 text-blue-700 border-blue-500/30')
                            }`}>
                              {sev}
                            </span>
                            <span className={`text-[14px] font-black ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>
                              {r?.dataset ? String(r.dataset) : 'Global Dataset'}
                              {r?.column ? ` · ${String(r.column)}` : ''}
                            </span>
                          </div>
                          <p className={`text-[12px] font-bold ${gxEnabled ? 'text-emerald-400/40' : 'text-black/40'}`}>{String(r?.issue_type || 'Unspecified Quality Issue')}</p>
                        </div>
                      </div>
                    </div>
                    
                    <div className={`mt-4 rounded-xl p-4 border transition-colors ${
                      gxEnabled ? 'bg-emerald-500/10 border-emerald-500/20 shadow-inner' : 'bg-[#0070AD]/5 border-[#0070AD]/10'
                    }`}>
                      <div className={`text-[11px] font-black uppercase tracking-widest mb-1 ${gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]'}`}>Recommended Fix</div>
                      <p className={`text-[13.5px] font-bold leading-relaxed ${gxEnabled ? 'text-zinc-100' : 'text-zinc-800'}`}>{String(r?.suggested_fix || '')}</p>
                    </div>

                    {r?.why_it_matters && (
                      <div className="mt-4 flex items-start gap-2 px-1">
                        <FaInfoCircle className={`mt-0.5 text-xs ${gxEnabled ? 'text-emerald-400/40' : 'text-[#0070AD]/60'}`} />
                        <div className={`text-[12px] font-medium leading-relaxed ${gxEnabled ? 'text-white/60' : 'text-black/60'}`}>
                          <span className={`font-bold ${gxEnabled ? 'text-white/80' : 'text-black/70'}`}>Impact:</span> {String(r.why_it_matters)}
                        </div>
                      </div>
                    )}

                    <div className="mt-5 flex flex-wrap gap-2.5">
                      {r?.example_sql && (
                        <motion.button
                          type="button"
                          whileHover={{ scale: 1.05, y: -2 }}
                          whileTap={{ scale: 0.95 }}
                          onClick={() => copy(String(r.example_sql))}
                          className={`flex items-center gap-2 rounded-xl border px-4 py-2 text-[11.5px] font-black shadow-sm transition-all ${
                            gxEnabled ? 'border-emerald-500/30 bg-emerald-500 text-black hover:bg-emerald-400' : 'border-[#0070AD]/20 bg-white text-[#0070AD] hover:bg-[#0070AD] hover:text-white hover:border-[#0070AD]'
                          }`}
                        >
                          <FaCode />
                          <span>COPY SQL FIX</span>
                        </motion.button>
                      )}
                      {r?.example_pandas && (
                        <motion.button
                          type="button"
                          whileHover={{ scale: 1.05, y: -2 }}
                          whileTap={{ scale: 0.95 }}
                          onClick={() => copy(String(r.example_pandas))}
                          className={`flex items-center gap-2 rounded-xl border px-4 py-2 text-[11.5px] font-black shadow-sm transition-all ${
                            gxEnabled ? 'border-emerald-500/20 bg-white/5 text-emerald-400 hover:bg-emerald-500/20' : 'border-[#12ABDB]/20 bg-white text-[#12ABDB] hover:bg-[#12ABDB] hover:text-white hover:border-[#12ABDB]'
                          }`}
                        >
                          <FaClipboard />
                          <span>COPY PANDAS CODE</span>
                        </motion.button>
                      )}
                    </div>
                  </motion.div>
                );
              })}

            </div>
          )}
        </div>
      ) : null}

      {/* Transform suggestions */}
      {enableTransformSuggestions ? (
        <div className={`rounded-2xl border p-6 shadow-2xl backdrop-blur-md transition-all duration-500 ${
          gxEnabled ? 'border-emerald-500/20 bg-[#000B14]/80' : 'border-[#12ABDB]/30 bg-white/60 shadow-[0_8px_32px_rgba(0,0,0,0.08)]'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-2xl shadow-lg ${
              gxEnabled ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-black shadow-emerald-500/20' : 'bg-gradient-to-br from-[#12ABDB] to-[#0070AD] text-white shadow-[#12ABDB]/20'
            }`}>
              <FaDatabase className="text-xl" />
            </div>
            <div>
              <h3 className={`text-lg font-black tracking-tight ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>Suggested Transformations</h3>
              <p className={`text-[12.5px] font-medium ${gxEnabled ? 'text-emerald-400/60' : 'text-black/50'}`}>Actions grouped by transformation type</p>
            </div>
          </div>

          {tfLoading ? (
            <div className="mt-8 flex flex-col items-center justify-center gap-3 py-12 text-center">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#12ABDB]/10 border-t-[#12ABDB]" />
              <p className="text-sm font-bold text-[#12ABDB] animate-pulse">Computing optimal transformations...</p>
            </div>
          ) : tfErr ? (
            <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-center">
              <p className="text-sm font-bold text-red-700">{tfErr}</p>
            </div>
          ) : tfByAction.length === 0 ? (
            <div className="mt-8 rounded-2xl border border-dashed border-[#12ABDB]/20 py-12 text-center">
              <p className="text-sm font-bold text-black/40">No transform suggestions available.</p>
            </div>
          ) : (
            <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {tfByAction.map((g) => (
                <details open key={g.action} className={`group/tf overflow-hidden rounded-2xl border transition-all hover:shadow-md ${
                  gxEnabled ? 'border-white/10 bg-white/5 hover:border-emerald-500/40 hover:bg-white/10' : 'border-black/10 bg-white/70 hover:border-[#12ABDB]/40'
                }`}>
                  <summary className={`cursor-pointer select-none p-4 text-[13px] font-black flex items-center justify-between gap-3 ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>
                    <div className="flex items-center gap-3">
                      <div className={`h-2 w-2 rounded-full group-open/tf:scale-150 transition-transform ${gxEnabled ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-[#12ABDB]'}`} />
                      <span className="uppercase tracking-tight">{g.action.replace(/_/g, ' ')}</span>
                    </div>
                    <span className={`flex h-6 min-w-[24px] items-center justify-center rounded-full px-2 text-[10px] font-black ${
                      gxEnabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[#12ABDB]/10 text-[#12ABDB]'
                    }`}>
                      {g.count}
                    </span>
                  </summary>
                  <div className={`border-t p-4 space-y-3 ${gxEnabled ? 'border-white/5 bg-black/20' : 'border-black/[0.05] bg-white/30'}`}>
                    {g.items.map((it, i) => (
                      <div key={i} className={`relative rounded-xl border p-3 shadow-sm ${
                        gxEnabled ? 'border-white/5 bg-white/5' : 'border-black/5 bg-white/80'
                      }`}>
                        <div className={`mb-1 text-[11px] font-black uppercase tracking-wider ${gxEnabled ? 'text-emerald-400' : 'text-[#12ABDB]'}`}>
                          {(it?._source ? `${it._source} · ` : '')}
                          {it?.dataset ?? 'global'}{it?.column ? ` · ${it.column}` : ''}
                        </div>
                        <div className={`text-[12.5px] font-bold leading-relaxed ${gxEnabled ? 'text-zinc-100' : 'text-zinc-800'}`}>
                          {String(it?.message || it?.issue_type || 'Potential transformation identified')}
                        </div>
                        {it?.recommendation && (
                          <div className={`mt-2 text-[11.5px] font-medium border-t pt-2 italic ${gxEnabled ? 'border-white/5 text-white/40' : 'border-black/5 text-black/50'}`}>
                            {it.recommendation}
                          </div>
                        )}
                      </div>
                    ))}
                    {g.items.length > 8 && (
                      <div className="text-[11px] font-black text-[#12ABDB]/60 text-center py-1">
                        + {g.items.length - 8} more suggestions in this category
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {/* Advanced diagnostics */}
      {showDiagnostics ? (
        <details className="rounded-xl border border-black/10 bg-white/80 p-4">
          <summary className="cursor-pointer select-none text-[12px] font-semibold text-zinc-900 flex items-center gap-2">
            <FaBug className="text-black/60" />
            Advanced diagnostics
          </summary>
          <div className="mt-3 space-y-3">
            {requestId ? (
              <div className="rounded-lg border border-black/10 bg-white/70 p-3">
                <div className="text-[11px] font-semibold text-black/70">request_id</div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <code className="text-[11px] text-zinc-900">{requestId}</code>
                  <button
                    type="button"
                    onClick={() => copy(requestId)}
                    className="rounded-md border border-black/10 bg-white/85 px-2 py-1 text-[11px] font-semibold text-zinc-900 hover:bg-white"
                  >
                    Copy
                  </button>
                </div>
              </div>
            ) : null}

            {timings ? (
              <div className="rounded-lg border border-black/10 bg-white/70 p-3">
                <div className="text-[11px] font-semibold text-black/70">timings</div>
                <pre className="mt-2 max-h-56 overflow-auto rounded-lg border border-black/10 bg-white/70 p-3 text-[11px] text-zinc-900">
                  {JSON.stringify(timings, null, 2)}
                </pre>
              </div>
            ) : null}

            {extractionErrors && extractionErrors.length ? (
              <div className="rounded-lg border border-black/10 bg-white/70 p-3">
                <div className="flex items-center gap-2 text-[11px] font-semibold text-black/70">
                  <FaExclamationTriangle className="text-amber-600" />
                  extraction_errors ({extractionErrors.length})
                </div>
                <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-black/10 bg-white/70 p-3 text-[11px] text-zinc-900">
                  {JSON.stringify(extractionErrors, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

