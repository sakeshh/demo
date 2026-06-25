'use client';

import { useMemo, useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FaChartBar, FaExclamationTriangle, FaCheckCircle, FaThumbsUp, FaThumbsDown, FaWrench, FaDatabase, FaTable, FaProjectDiagram, FaArrowRight } from 'react-icons/fa';
import ReportEnhancements from '@/components/ReportEnhancements';
import { sourceRootLabel } from '@/lib/assessmentDisplay';

interface DataAssessmentReportProps {
  files: string[];
  database: string;
  includeTransformSuggestions?: boolean;
  onIncludeTransformSuggestionsChange?: (v: boolean) => void;
  includeDqRecommendations?: boolean;
  onIncludeDqRecommendationsChange?: (v: boolean) => void;
  onComplete: (data: any) => void;
  onFeedback: (liked: boolean, comment?: string) => void;
  approvedSemantics?: Record<string, Record<string, string>>;
}

type Severity = 'high' | 'medium' | 'low';

type BackendAssessment = {
  datasets?: Record<
    string,
    {
      row_count?: number;
      column_count?: number;
      source_root?: string;
      columns?: Record<
        string,
        {
          dtype?: string;
          null_percentage?: number;
          unique_count?: number;
          semantic_type?: string;
          candidate_primary_key?: boolean;
        }
      >;
    }
  >;
  relationships?: Array<{
    dataset_a?: string;
    column_a?: string;
    dataset_b?: string;
    column_b?: string;
    cardinality?: string;
    overlap_count?: number;
  }>;
  data_quality_issues?: {
    datasets?: Record<
      string,
      {
        summary?: {
          issue_count?: number;
          high_severity?: number;
          medium_severity?: number;
          low_severity?: number;
          dq_score_0_100?: number;
        };
        issues?: Array<{
          severity?: Severity | string;
          type?: string;
          column?: string;
          count?: number;
          message?: string;
          recommendation?: string;
        }>;
      }
    >;
    global_issues?: Record<string, any>;
  };
  dq_recommendations?: any;
};

type UiDatasetSummary = {
  name: string;
  sourceLabel: string;
  rows: number;
  cols: number;
  issues: number;
  high: number;
  med: number;
  low: number;
  dqScore?: number;
};

function normalizeSeverity(s: any): Severity {
  const t = String(s || '').toLowerCase();
  if (t === 'high') return 'high';
  if (t === 'medium') return 'medium';
  return 'low';
}

export default function DataAssessmentReport({
  files,
  database,
  includeTransformSuggestions = true,
  onIncludeTransformSuggestionsChange,
  includeDqRecommendations = true,
  onIncludeDqRecommendationsChange,
  onComplete,
  onFeedback,
  approvedSemantics,
}: DataAssessmentReportProps) {
  const [assessing, setAssessing] = useState(true);
  const [progress, setProgress] = useState(0);
  const [assessment, setAssessment] = useState<BackendAssessment | null>(null);
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [transformEnabled, setTransformEnabled] = useState<boolean>(Boolean(includeTransformSuggestions));
  const [transformSuggestions, setTransformSuggestions] = useState<any>(null);
  const [transformLoading, setTransformLoading] = useState(false);
  const [dqRecEnabled, setDqRecEnabled] = useState<boolean>(Boolean(includeDqRecommendations));

  const summaries: UiDatasetSummary[] = useMemo(() => {
    const datasets = assessment?.datasets || {};
    const dq = assessment?.data_quality_issues?.datasets || {};
    return Object.entries(datasets).map(([name, meta]) => {
      const summ = dq?.[name]?.summary || {};
      return {
        name,
        sourceLabel: sourceRootLabel(meta?.source_root),
        rows: Number(meta?.row_count ?? 0) || 0,
        cols: Number(meta?.column_count ?? 0) || 0,
        issues: Number(summ?.issue_count ?? 0) || 0,
        high: Number(summ?.high_severity ?? 0) || 0,
        med: Number(summ?.medium_severity ?? 0) || 0,
        low: Number(summ?.low_severity ?? 0) || 0,
        dqScore: summ?.dq_score_0_100 !== undefined ? Number(summ.dq_score_0_100) : undefined,
      };
    });
  }, [assessment]);

  useEffect(() => {
    runAssessment();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep local state in sync with parent toggle if provided
  useEffect(() => {
    setTransformEnabled(Boolean(includeTransformSuggestions));
  }, [includeTransformSuggestions]);

  useEffect(() => {
    setDqRecEnabled(Boolean(includeDqRecommendations));
  }, [includeDqRecommendations]);

  const getSessionId = () => {
    if (typeof window === 'undefined') return 'default';
    return window.localStorage.getItem('dharaSessionId') || 'default';
  };

  const parseSourceToken = (token: string): { kind: 'sql' | 'blob' | 'streams' | 'unknown'; absIndex: number } => {
    const parts = String(token || '').split(':');
    const kind = (parts[1] as any) || 'unknown';
    const absIndex = Number(parts[2] || 0);
    return { kind, absIndex: Number.isFinite(absIndex) ? absIndex : 0 };
  };

  const normalizeType = (t: any): string => {
    const s = String(t || '').toLowerCase();
    if (s.includes('azure_blob')) return 'azure_blob';
    if (s.includes('filesystem')) return 'filesystem';
    if (s.includes('database')) return 'database';
    return s || 'unknown';
  };

  const runAssessment = async () => {
    setAssessing(true);
    setProgress(5);
    setTransformSuggestions(null);
    try {
      const sid = getSessionId();
      const src = parseSourceToken(database);
      const sourcesRes = await fetch('/api/sources');
      const sourcesJson = await sourcesRes.json().catch(() => null);
      const locs = Array.isArray(sourcesJson?.locations) ? sourcesJson.locations : [];
      const absList = locs.map((l: any) => ({ index: Number(l?.index ?? 0), type: normalizeType(l?.type) }));

      const relIndex = (type: string, absIndex: number) => {
        const only = absList
          .filter((x: { index: number; type: string }) => x.type === type)
          .map((x: { index: number; type: string }) => x.index);
        const pos = only.indexOf(absIndex);
        return pos >= 0 ? pos : 0;
      };

      // Store deterministic selection context for the backend session.
      const context: any = {};
      if (src.kind === 'sql') {
        context.last_table_list = files;
        context.selected_tables = files;
        context.selected_db_location_index = relIndex('database', src.absIndex);
      } else if (src.kind === 'blob') {
        context.last_blob_list = files;
        context.selected_blob_files = files;
        context.selected_blob_location_index = relIndex('azure_blob', src.absIndex);
      } else if (src.kind === 'streams') {
        context.last_local_file_list = files;
        context.selected_local_files = files;
        context.selected_fs_location_index = relIndex('filesystem', src.absIndex);
      }

      if (approvedSemantics) {
        context.approved_semantics = approvedSemantics;
      }

      setProgress(15);
      await fetch('/api/session-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, context }),
      });

      setProgress(25);
      const cmd =
        src.kind === 'sql'
          ? 'assess selected tables'
          : src.kind === 'blob'
            ? 'assess selected files'
            : src.kind === 'streams'
              ? 'assess selected local files'
              : 'help';

      const jobRes = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: 'assess',
          input: {
            sessionId: sid,
            messages: [{ role: 'user', content: cmd }]
          }
        }),
      });
      
      const jobData = await jobRes.json().catch(() => null);
      if (!jobRes.ok || !jobData?.job_id) {
        throw new Error(jobData?.message || 'Failed to start assessment job');
      }
      
      const jobId = jobData.job_id;
      let jobStatus = 'pending';
      let jobResult: any = null;
      
      while (jobStatus !== 'completed' && jobStatus !== 'failed' && jobStatus !== 'succeeded') {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const statusRes = await fetch(`/api/assess/status/${jobId}`);
        const statusData = await statusRes.json().catch(() => null);
        if (!statusRes.ok || !statusData) {
          throw new Error(statusData?.message || 'Failed to get job status');
        }
        jobStatus = statusData.status;
        setProgress(Math.min(95, Math.max(25, statusData.progress || 0)));
        if (jobStatus === 'completed' || jobStatus === 'succeeded') {
          jobResult = statusData.result;
        } else if (jobStatus === 'failed') {
          throw new Error(statusData.error || 'Assessment job failed');
        }
      }

      const payload = jobResult;
      const result: BackendAssessment | null = payload?.result ?? payload ?? null;
      setAssessment(result);
      setReportMarkdown(typeof payload?.report_markdown === 'string' ? payload.report_markdown : null);
      setReportHtml(typeof payload?.report_html === 'string' ? payload.report_html : null);

      let suggestionsOut: any = null;
      if (transformEnabled && result) {
        setTransformLoading(true);
        try {
          const tr = await fetch('/api/transform-suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assessment_result: result }),
          });
          const trJson = await tr.json().catch(() => null);
          suggestionsOut = trJson?.suggestions ?? null;
          setTransformSuggestions(suggestionsOut);
        } catch {
          suggestionsOut = null;
          setTransformSuggestions(null);
        } finally {
          setTransformLoading(false);
        }
      }

      if (dqRecEnabled && result && !result.dq_recommendations) {
        try {
          const res = await fetch('/api/dq-recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data_quality: result.data_quality_issues || result, user_intent: title }),
          });
          const j = await res.json().catch(() => null);
          if (j?.recommendations) {
            result.dq_recommendations = j.recommendations;
          }
        } catch (e) {
          console.error("Failed to pre-fetch DQ recommendations:", e);
        }
      }

      setProgress(100);
      onComplete({
        result,
        report_markdown: payload?.report_markdown,
        report_html: payload?.report_html,
        report_files: payload?.report_files,
        transform_suggestions: suggestionsOut,
      });
    } catch (err: any) {
      setAssessment(null);
      setReportMarkdown(null);
      setReportHtml(null);
      onComplete(null);
    } finally {
      setAssessing(false);
    }
  };

  const handleLike = () => {
    onFeedback(true);
    setShowFeedback(false);
  };

  const handleDislike = () => {
    const comment = prompt('What would you like us to improve?');
    onFeedback(false, comment || undefined);
    setShowFeedback(false);
    
    setTimeout(() => {
      alert('Thank you for your feedback! Re-assessing data with improvements...');
      setAssessing(true);
      setProgress(0);
      runAssessment();
    }, 500);
  };

  if (assessing) {
    return (
      <div className="flex flex-col items-center justify-center space-y-10 py-16">
        <div className="relative">
          <div className="absolute inset-0 scale-150 blur-3xl bg-gradient-to-tr from-[#0070AD]/20 to-[#12ABDB]/20 animate-pulse" />
          <div className="relative flex h-24 w-24 items-center justify-center rounded-3xl bg-white shadow-2xl">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-[#0070AD]/10 border-t-[#0070AD]" />
          </div>
        </div>
        
        <div className="text-center space-y-3">
          <h2 className="text-4xl font-black tracking-tight text-zinc-900">Intelligent Assessment</h2>
          <p className="text-lg font-medium text-black/40">Running deep analysis on your datasets...</p>
        </div>

        <div className="w-full max-w-md space-y-4">
          <div className="relative h-3 w-full bg-black/5 rounded-full overflow-hidden border border-black/5">
            <motion.div
              className="h-full bg-gradient-to-r from-[#0070AD] via-[#12ABDB] to-[#0070AD] bg-[length:200%_auto]"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%`, backgroundPosition: ['0% 0%', '100% 0%'] }}
              transition={{ width: { duration: 0.5 }, backgroundPosition: { duration: 2, repeat: Infinity, ease: 'linear' } }}
            />
          </div>
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] font-black uppercase tracking-widest text-black/30">Progress</span>
            <span className="text-xl font-black text-[#0070AD]">{progress}%</span>
          </div>
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          {['Schema Scan', 'Quality Audit', 'Relationship Mapping', 'AI Synthesis'].map((task, idx) => (
            <motion.div
              key={task}
              initial={{ opacity: 0, y: 10 }}
              animate={{ 
                opacity: progress > idx * 25 ? 1 : 0.4,
                y: 0,
                scale: progress > idx * 25 ? 1 : 0.95
              }}
              className={`flex items-center gap-2 rounded-2xl border px-4 py-2.5 text-sm font-bold shadow-sm transition-all ${
                progress > idx * 25 
                  ? 'border-[#0070AD]/30 bg-white text-[#0070AD] shadow-[#0070AD]/10' 
                  : 'border-black/5 bg-black/5 text-black/30'
              }`}
            >
              {progress > idx * 25 ? <FaCheckCircle className="text-emerald-500" /> : <div className="h-3 w-3 rounded-full border-2 border-current" />}
              <span>{task}</span>
            </motion.div>
          ))}
        </div>
      </div>
    );
  }

  const title = files.length === 1 ? `Assessment Report of ${files[0]}` : 'Assessment Report';

  const relationships = Array.isArray(assessment?.relationships) ? assessment!.relationships! : [];
  const globalIssues = assessment?.data_quality_issues?.global_issues || null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-zinc-900 mb-2">{title}</h2>
          <p className="text-black/60">Datasets summary, relationships, and issues</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleLike}
            className="p-3 bg-[#0070AD]/10 text-[#0070AD] rounded-lg hover:bg-[#0070AD]/15 transition-colors"
            title="Like this assessment"
          >
            <FaThumbsUp className="text-xl" />
          </button>
          <button
            onClick={handleDislike}
            className="p-3 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
            title="Dislike this assessment"
          >
            <FaThumbsDown className="text-xl" />
          </button>
        </div>
      </div>

      {/* Transform suggestions toggle */}
      <div className="border border-black/10 rounded-lg p-4 bg-white/90 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[#0070AD]/10 text-[#0070AD]">
            <FaWrench />
          </div>
          <div>
            <div className="font-semibold text-zinc-900">Include transformation suggestions</div>
            <div className="text-sm text-black/60">Generates suggested cleaning/transform actions from detected issues</div>
          </div>
        </div>
        <motion.button
          type="button"
          onClick={() => {
            const next = !transformEnabled;
            setTransformEnabled(next);
            if (onIncludeTransformSuggestionsChange) onIncludeTransformSuggestionsChange(next);
          }}
          className={`px-4 py-2 rounded-xl border text-sm font-semibold transition-colors ${
            transformEnabled
              ? 'border-[#0070AD]/50 bg-[#0070AD]/10 text-[#0070AD] hover:bg-[#0070AD]/15'
              : 'border-black/10 bg-white/80 text-black/60 hover:bg-white'
          }`}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {transformEnabled ? 'On' : 'Off'}
        </motion.button>
      </div>

      {/* DQ recommendations toggle */}
      <div className="border border-black/10 rounded-lg p-4 bg-white/90 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[#0070AD]/10 text-[#0070AD]">
            <FaWrench />
          </div>
          <div>
            <div className="font-semibold text-zinc-900">Generate cleaning recommendations (LLM)</div>
            <div className="text-sm text-black/60">Creates a prioritized plan to clean/fix issues (falls back if LLM not configured)</div>
          </div>
        </div>
        <motion.button
          type="button"
          onClick={() => {
            const next = !dqRecEnabled;
            setDqRecEnabled(next);
            if (onIncludeDqRecommendationsChange) onIncludeDqRecommendationsChange(next);
          }}
          className={`px-4 py-2 rounded-xl border text-sm font-semibold transition-colors ${
            dqRecEnabled
              ? 'border-[#0070AD]/50 bg-[#0070AD]/10 text-[#0070AD] hover:bg-[#0070AD]/15'
              : 'border-black/10 bg-white/80 text-black/60 hover:bg-white'
          }`}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {dqRecEnabled ? 'On' : 'Off'}
        </motion.button>
      </div>

      {/* Datasets summary dashboard */}
      <div className="rounded-3xl border border-[#0070AD]/30 bg-white/60 p-8 shadow-[0_8px_32px_rgba(0,0,0,0.08)] backdrop-blur-md">
        <div className="mb-8 flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0070AD] to-[#12ABDB] text-white shadow-xl shadow-[#0070AD]/20">
              <FaChartBar className="text-2xl" />
            </div>
            <div>
              <h3 className="text-xl font-black tracking-tight text-zinc-900">Dataset Intelligence Summary</h3>
              <p className="text-[14px] font-medium text-black/50">High-level overview across all selected sources</p>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-[10px] font-black uppercase tracking-widest text-black/40">Total Rows Processed</div>
              <div className="text-2xl font-black text-[#0070AD]">
                {summaries.reduce((acc, s) => acc + s.rows, 0).toLocaleString()}
              </div>
            </div>
          </div>
        </div>

        {summaries.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-black/10 py-12 text-center text-black/40">
            No dataset metrics identified.
          </div>
        ) : (
          <div className="group/table relative overflow-hidden rounded-2xl border border-[#0070AD]/20 bg-white/50 shadow-sm transition-all hover:shadow-md">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="bg-gradient-to-r from-[#0070AD]/10 to-[#12ABDB]/10 backdrop-blur-xl">
                    <th className="py-4 px-4 text-left font-black uppercase tracking-wider text-[#0070AD]">Dataset</th>
                    <th className="py-4 px-4 text-left font-black uppercase tracking-wider text-[#0070AD]">Source</th>
                    <th className="py-4 px-4 text-right font-black uppercase tracking-wider text-[#0070AD]">Rows</th>
                    <th className="py-4 px-4 text-right font-black uppercase tracking-wider text-[#0070AD]">Cols</th>
                    <th className="py-4 px-4 text-right font-black uppercase tracking-wider text-[#0070AD]">High Issues</th>
                    <th className="py-4 px-4 text-right font-black uppercase tracking-wider text-[#0070AD]">Quality Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5">
                  {summaries.map((r) => {
                    const totalIssues = r.high + r.med + r.low;
                    const score = r.dqScore !== undefined ? r.dqScore : Math.max(0, 100 - (r.high * 5 + r.med * 2 + r.low * 0.5) / (r.cols || 1));
                    return (
                      <tr key={r.name} className="transition-colors hover:bg-[#12ABDB]/5 group/row">
                        <td className="py-3.5 px-4 font-black text-zinc-900">{r.name}</td>
                        <td className="py-3.5 px-4">
                          <span className="rounded-full bg-black/5 px-2 py-0.5 text-[11px] font-bold text-black/50 uppercase">
                            {r.sourceLabel}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-right font-bold text-zinc-700">{r.rows.toLocaleString()}</td>
                        <td className="py-3.5 px-4 text-right font-bold text-zinc-700">{r.cols.toLocaleString()}</td>
                        <td className="py-3.5 px-4 text-right font-black text-red-600">
                          {r.high > 0 ? (
                            <span className="flex items-center justify-end gap-1">
                              <FaExclamationTriangle className="text-[10px]" />
                              {r.high}
                            </span>
                          ) : '0'}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-black/5">
                              <div 
                                className={`h-full transition-all ${score > 80 ? 'bg-emerald-500' : score > 50 ? 'bg-amber-500' : 'bg-red-500'}`}
                                style={{ width: `${score}%` }}
                              />
                            </div>
                            <span className={`w-8 text-right font-black ${score > 80 ? 'text-emerald-600' : score > 50 ? 'text-amber-600' : 'text-red-600'}`}>
                              {Math.round(score)}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Best UX panels: cleaning recommendations + transforms + advanced diagnostics */}
      {assessment ? (
        <ReportEnhancements
          result={{
            ...assessment,
            // allow showing the already-generated transform suggestions, if present
            transform_suggestions: transformSuggestions ? { sources: { result: transformSuggestions } } : undefined,
          }}
          userIntent={title}
          enableDqRecommendations={dqRecEnabled}
          enableTransformSuggestions={transformEnabled}
          variant="pipeline"
        />
      ) : null}

      {/* Relationships */}
      <div className="rounded-2xl border border-[#0070AD]/30 bg-white/60 p-6 shadow-[0_8px_32px_rgba(0,0,0,0.08)] backdrop-blur-md">
        <div className="mb-6 flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0070AD] to-[#12ABDB] text-white">
            <FaCheckCircle className="text-xl" />
          </div>
          <div>
            <h3 className="text-lg font-black tracking-tight text-zinc-900">Data Relationships</h3>
            <p className="text-[12.5px] font-medium text-black/50">Identified joins and overlap between sources</p>
          </div>
        </div>
        
        {relationships.length === 0 ? (
          <div className="rounded-xl border border-dashed border-black/10 py-8 text-center text-black/40">
            No inter-dataset relationships identified.
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-black/10 bg-white/50">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-black/[0.03] text-[11px] font-black uppercase tracking-widest text-black/40">
                    <th className="py-3 px-4 text-left">Dataset A</th>
                    <th className="py-3 px-4 text-left text-[#0070AD]">Primary Key</th>
                    <th className="py-3 px-4 text-left">Dataset B</th>
                    <th className="py-3 px-4 text-left text-[#0070AD]">Foreign Key</th>
                    <th className="py-3 px-4 text-center">Cardinality</th>
                    <th className="py-3 px-4 text-right">Shared Count</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5">
                  {relationships.map((r, i) => (
                    <tr key={i} className="transition-colors hover:bg-black/[0.02]">
                      <td className="py-3 px-4 font-black text-zinc-800">{r.dataset_a}</td>
                      <td className="py-3 px-4 font-mono text-[12px] text-[#0070AD]">{r.column_a}</td>
                      <td className="py-3 px-4 font-black text-zinc-800">{r.dataset_b}</td>
                      <td className="py-3 px-4 font-mono text-[12px] text-[#0070AD]">{r.column_b}</td>
                      <td className="py-3 px-4 text-center">
                        <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-[10px] font-black text-blue-600 uppercase tracking-tighter">
                          {r.cardinality}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-black text-zinc-900">{(r.overlap_count ?? 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Global issues */}
      <div className="border border-black/10 rounded-lg p-6 bg-white/90">
        <div className="flex items-center gap-3 mb-4">
          <FaExclamationTriangle className="text-amber-500" />
          <h3 className="text-xl font-bold text-zinc-900">Global issues</h3>
        </div>
        {!globalIssues ? (
          <div className="text-sm text-black/60">No global issues returned.</div>
        ) : (
          <pre className="text-xs text-zinc-900 whitespace-pre-wrap font-mono bg-black/5 border border-black/10 rounded-lg p-4 overflow-auto max-h-80">
            {JSON.stringify(globalIssues, null, 2)}
          </pre>
        )}
      </div>

      {/* Backend report previews (optional) */}
      {(reportMarkdown || reportHtml) && (
        <div className="border border-black/10 rounded-lg p-6 bg-white/90 space-y-3">
          <h3 className="text-xl font-bold text-zinc-900">Generated report artifacts</h3>
          {reportMarkdown && (
            <details className="bg-white/80 border border-black/10 rounded-lg p-4">
              <summary className="cursor-pointer font-semibold text-zinc-900">Markdown (preview)</summary>
              <pre className="mt-3 text-xs text-zinc-900 whitespace-pre-wrap font-mono">{reportMarkdown}</pre>
            </details>
          )}
          {reportHtml && (
            <details className="bg-white/80 border border-black/10 rounded-lg p-4">
              <summary className="cursor-pointer font-semibold text-zinc-900">HTML (preview)</summary>
              <pre className="mt-3 text-xs text-zinc-900 whitespace-pre-wrap font-mono">{reportHtml.slice(0, 4000)}{reportHtml.length > 4000 ? '\n…(truncated preview)…' : ''}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
