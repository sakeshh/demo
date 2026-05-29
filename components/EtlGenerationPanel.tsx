'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaCode, FaChevronRight, FaExclamationTriangle, FaCheck, FaCopy, FaTrash, FaDownload, FaShieldAlt } from 'react-icons/fa';
import EtlLineageVisualizer, { type LineageMap } from '@/components/EtlLineageVisualizer';
import {
  EngineRecommendationCard,
  RelationshipsCard,
  ManyToManyCard,
  OverallReadinessBanner,
  StepEvidenceTooltip,
  applyEngineRecommendation,
  getPlanFromRecord,
  getStepNarration,
  type EngineRecommendation,
  type StepEvidence,
} from '@/components/EtlIntelligencePreview';
import ManualReviewPanel from '@/components/ManualReviewPanel';
import GenerationModeSelector from '@/components/GenerationModeSelector';
import RequirementsPhasePanel from '@/components/RequirementsPhasePanel';
import RequirementValidator from '@/components/RequirementValidator';
import ETLCodeTabView from '@/components/ETLCodeTabView';
import { DQGateResult, ManualReviewItem, ValidationResult } from '@/types/pipeline';

type Step = 'rules' | 'plan' | 'preview' | 'code';

export type EtlEngine = 'python' | 'sql' | 'spark' | 'adf';

type StepRow = {
  id: string;
  dataset: string;
  order: number;
  column: string | null;
  action: string;
  bucket?: string;
};

function bucketBadgeClass(bucket: string | undefined, dm: boolean): string {
  const b = (bucket || 'auto').toLowerCase();
  if (b === 'blocked') return dm ? 'bg-rose-500/30 text-rose-100' : 'bg-rose-100 text-rose-900';
  if (b === 'review') return dm ? 'bg-amber-500/30 text-amber-100' : 'bg-amber-100 text-amber-900';
  return dm ? 'bg-emerald-500/25 text-emerald-100' : 'bg-emerald-100 text-emerald-900';
}

function planToRows(plan: Record<string, unknown>): StepRow[] {
  const dsPlan = (plan.datasets || {}) as Record<string, { steps?: Record<string, unknown>[] }>;
  const out: StepRow[] = [];
  for (const [ds, block] of Object.entries(dsPlan)) {
    for (const st of block.steps || []) {
      const order = Number(st.order ?? 0);
      const col = (st.column as string | null | undefined) ?? null;
      const action = String(st.action ?? '');
      out.push({
        id: `${ds}|${order}|${col}|${action}`,
        dataset: ds,
        order,
        column: col,
        action,
        bucket: typeof st.bucket === 'string' ? st.bucket : 'auto',
      });
    }
  }
  return out.sort((a, b) => a.dataset.localeCompare(b.dataset) || a.order - b.order);
}

function rowsToPlan(base: Record<string, unknown>, rows: StepRow[]): Record<string, unknown> {
  const byDs: Record<string, StepRow[]> = {};
  for (const r of rows) {
    if (!byDs[r.dataset]) byDs[r.dataset] = [];
    byDs[r.dataset].push(r);
  }
  const datasets: Record<string, { steps: Record<string, unknown>[] }> = {};
  for (const [ds, list] of Object.entries(byDs)) {
    const sorted = [...list].sort((a, b) => a.order - b.order);
    datasets[ds] = {
      steps: sorted.map((r, i) => ({
        order: i + 1,
        column: r.column,
        action: r.action,
        bucket: r.bucket || 'auto',
      })),
    };
  }
  return { ...base, datasets };
}

function parseCodegenEngine(raw: string | undefined): EtlEngine {
  const e = (raw || 'python').toLowerCase();
  if (e === 'sql' || e === 'ansi' || e === 'tsql') return 'sql';
  if (e === 'spark' || e === 'pyspark') return 'spark';
  if (e === 'adf') return 'adf';
  return 'python';
}

export type EtlPipelineMode = 'full' | 'requirements' | 'etl';

export interface EtlGenerationPanelProps {
  sessionId: string;
  assessment: Record<string, unknown> | null;
  variant?: 'pipeline' | 'chat';
  darkMode?: boolean;
  pipelineMode?: EtlPipelineMode;
  onContinueToEtlStep?: () => void;
  onEditPlanInRequirements?: () => void;
  onCodeGenerated?: (code: string) => void;
  onContinueAfterCode?: () => void;

  // Sprint 7 extensions
  gateResult?: DQGateResult | null;
  semanticOverrides?: Record<string, any>;
}

export default function EtlGenerationPanel({
  sessionId,
  assessment,
  variant = 'pipeline',
  darkMode = false,
  pipelineMode = 'full',
  onContinueToEtlStep,
  onEditPlanInRequirements,
  onCodeGenerated,
  onContinueAfterCode,
  gateResult = null,
  semanticOverrides = {},
}: EtlGenerationPanelProps) {
  const dm = darkMode && variant === 'chat';
  const shell = dm
    ? 'rounded-3xl border border-[#0070AD]/30 bg-[#001a2e]/90 p-6 shadow-sm text-zinc-100'
    : 'rounded-3xl border border-black/10 bg-white/70 p-6 shadow-sm';
  const sub = dm ? 'text-[#0070AD]/80' : 'text-black/55';
  const label = dm ? 'text-[#0070AD]/70' : 'text-black/45';
  const field = dm
    ? 'rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-zinc-100 placeholder:text-white/30'
    : 'rounded-xl border border-black/10 bg-white px-3 py-2 text-sm text-zinc-900';

  const [step, setStep] = useState<Step>(() => (pipelineMode === 'etl' ? 'preview' : 'rules'));
  const [etlSessionLoading, setEtlSessionLoading] = useState(pipelineMode === 'etl');
  const [engine, setEngine] = useState<EtlEngine>('python');
  const [engineUserOverride, setEngineUserOverride] = useState(false);
  const [sqlDialect, setSqlDialect] = useState<'tsql' | 'ansi'>('tsql');
  const [neverDropRows, setNeverDropRows] = useState(false);
  const [targetDestination, setTargetDestination] = useState<'dataframe_only' | 'new_path' | 'overwrite'>(
    'dataframe_only'
  );
  const [targetPath, setTargetPath] = useState('cleaned/');
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [planValidationErrors, setPlanValidationErrors] = useState<string[]>([]);
  const [tenantId, setTenantId] = useState('default');
  const [tenantOptions, setTenantOptions] = useState<string[]>(['default', 'acme']);
  
  // Phase 1 inputs
  const [requiredColumns, setRequiredColumns] = useState('');
  const [excludeColumns, setExcludeColumns] = useState('');
  const [outlierStrategy, setOutlierStrategy] = useState<'flag' | 'clip' | 'cap'>('flag');

  // Phase 2 inputs
  const [notes, setNotes] = useState('');
  const [scdType, setScdType] = useState<'type1' | 'type2' | 'none'>('none');
  const [hashPhone, setHashPhone] = useState(false);
  const [maskEmail, setMaskEmail] = useState(false);

  // Sprint 7 dynamic states
  const [dqThreshold, setDqThreshold] = useState(70);
  const [generationMode, setGenerationMode] = useState<'cleanse_only' | 'full'>('full');
  const [forceUnlock, setForceUnlock] = useState(false);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planJson, setPlanJson] = useState('');
  const [planTab, setPlanTab] = useState<'table' | 'json'>('table');
  const [planRows, setPlanRows] = useState<StepRow[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  
  // Tabbed view and split code states
  const [activeCodeTab, setActiveCodeTab] = useState<'phase1' | 'phase2' | 'review'>('phase1');
  const [phase1Code, setPhase1Code] = useState<string | null>(null);
  const [phase2Code, setPhase2Code] = useState<string | null>(null);
  const [manualReviewItemsState, setManualReviewItemsState] = useState<ManualReviewItem[]>([]);
  const [sqlQualityScore, setSqlQualityScore] = useState<{ score: number; grade: string; warnings_count: number; critical_count: number } | null>(null);

  const [validationOk, setValidationOk] = useState<boolean | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [artifactPath, setArtifactPath] = useState<string | null>(null);
  const [generatedBy, setGeneratedBy] = useState<string | null>(null);
  const [isDraft, setIsDraft] = useState(false);
  const [useAiCodegen, setUseAiCodegen] = useState(false);
  const [generateStatus, setGenerateStatus] = useState<string | null>(null);

  useEffect(() => {
    if (plan) {
      setPlanJson(JSON.stringify(plan, null, 2));
      setPlanRows(planToRows(plan));
    }
  }, [plan]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/etl/tenants');
        const data = await res.json().catch(() => null);
        if (cancelled || !res.ok || !data?.ok) return;
        const ids = Array.isArray(data.tenants) ? data.tenants.filter((t: unknown) => typeof t === 'string') : [];
        if (ids.length > 0) setTenantOptions(ids);
      } catch {
        /* keep defaults */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const parseQualityScore = (codeText: string) => {
    if (!codeText) return null;
    const scoreMatch = codeText.match(/Quality\s+Score:\s*(\d+)/i);
    const gradeMatch = codeText.match(/Grade:\s*([A-F])/i);
    const warningsMatch = codeText.match(/Warnings:\s*(\d+)/i);
    const criticalMatch = codeText.match(/Critical\s*Errors:\s*(\d+)/i);
    
    if (scoreMatch || gradeMatch) {
      return {
        score: scoreMatch ? Number(scoreMatch[1]) : 80,
        grade: gradeMatch ? gradeMatch[1] : 'B',
        warnings_count: warningsMatch ? Number(warningsMatch[1]) : 0,
        critical_count: criticalMatch ? Number(criticalMatch[1]) : 0,
      };
    }
    return null;
  };

  const businessRulesPayload = useCallback(() => {
    const req = requiredColumns
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const excl = excludeColumns
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    let finalNotes = notes.trim();
    if (hashPhone) {
      finalNotes += '\nHash phone columns for privacy compliance.';
    }
    if (maskEmail) {
      finalNotes += '\nMask email columns for privacy compliance.';
    }

    const datasets = Object.keys(assessment?.datasets || {});
    const scdConfig = datasets.reduce((acc, dsName) => {
      acc[dsName] = { type: scdType };
      return acc;
    }, {} as Record<string, any>);

    return {
      never_drop_rows: neverDropRows,
      required_columns: req,
      exclude_columns: excl,
      outlier_strategy: outlierStrategy,
      notes: finalNotes,
      dq_threshold: dqThreshold,
      generation_mode: generationMode,
      force_unlock: forceUnlock ? datasets : [],
      semantic_overrides: semanticOverrides || {},
      scd: scdConfig,
    };
  }, [neverDropRows, requiredColumns, excludeColumns, outlierStrategy, notes, hashPhone, maskEmail, dqThreshold, generationMode, forceUnlock, semanticOverrides, assessment]);

  const stepBadges = useMemo(() => {
    if (pipelineMode === 'requirements') return ['rules', 'plan'] as const;
    if (pipelineMode === 'etl') return ['preview', 'code'] as const;
    return ['rules', 'plan', 'preview', 'code'] as const;
  }, [pipelineMode]);

  const badgeLabel = (s: string) => {
    const map: Record<string, string> = {
      rules: 'RULES',
      plan: 'PLAN',
      preview: 'PREVIEW',
      code: 'CODE',
    };
    return map[s] || s.toUpperCase();
  };

  useEffect(() => {
    if (pipelineMode !== 'etl') {
      setEtlSessionLoading(false);
      return;
    }
    let cancelled = false;
    setEtlSessionLoading(true);
    setErr(null);
    (async () => {
      try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        const flow = data?.session?.context?.etl_flow;
        if (!flow?.approved_plan) {
          setErr(
            'Complete ETL rules and plan on the Requirements step first (confirm the plan to approve it).',
          );
          setEtlSessionLoading(false);
          return;
        }
        setPlan(flow.approved_plan as Record<string, unknown>);
        if (flow.preview) setPreview(flow.preview as Record<string, unknown>);
        if (flow.lineage) setLineage(flow.lineage as Record<string, unknown>);
        const ce = parseCodegenEngine(flow.codegen_engine ?? flow.target_engine);
        setEngine(ce);
        const sd = flow.sql_dialect;
        if (sd === 'ansi' || sd === 'tsql') setSqlDialect(sd);
        
        // Restore codes
        if (typeof flow.code === 'string' && flow.code.trim().length > 0) {
          setPhase1Code(flow.code);
          setValidationOk(flow.validation_ok != null ? Boolean(flow.validation_ok) : null);
          setValidationErrors(Array.isArray(flow.validation_errors) ? flow.validation_errors : []);
          setArtifactPath(typeof flow.artifact_rel_path === 'string' ? flow.artifact_rel_path : null);
          
          const score = parseQualityScore(flow.code);
          setSqlQualityScore(score);
          setStep('code');
        } else {
          setStep('preview');
        }
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : 'Failed to load session');
      } finally {
        if (!cancelled) setEtlSessionLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pipelineMode, sessionId]);

  const runPlan = async () => {
    if (!assessment) {
      setErr('No assessment loaded yet.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const planEngine = engine === 'spark' || engine === 'adf' ? 'python' : engine;
      const res = await fetch('/api/etl/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          business_rules: businessRulesPayload(),
          assessment_result: assessment,
          engine: planEngine,
          codegen_engine: engine,
          sql_dialect: sqlDialect,
          target_destination: targetDestination,
          target_path: targetDestination === 'new_path' ? targetPath : undefined,
          tenant_id: tenantId,
          engine_user_override: engineUserOverride,
        }),
      });
      const data = await res.json().catch(() => null);
      const blocked = Array.isArray(data?.blocked) ? data.blocked : [];
      const builtPlan = (data?.plan || null) as Record<string, unknown> | null;
      if (!res.ok) {
        setErr(data?.message || data?.error || `Plan failed (${res.status})`);
        return;
      }
      if (!data?.ok) {
        const perrs = Array.isArray(data.plan_validation_errors) ? data.plan_validation_errors : [];
        setPlanValidationErrors(perrs);
        if (builtPlan) setPlan(builtPlan);
        setErr(
          data?.message ||
            (blocked.length
              ? `Blocked: ${blocked.map((b: { message?: string }) => b.message || JSON.stringify(b)).join(' | ')}`
              : `Plan has validation warnings (${perrs.length}). Review before confirming.`)
        );
        setStep('plan');
        return;
      }
      if (blocked.length > 0) {
        setErr(`Blocked: ${blocked.map((b: { message?: string }) => b.message || JSON.stringify(b)).join(' | ')}`);
        setPlan(builtPlan);
        setStep('plan');
        return;
      }
      setPlan(builtPlan);
      if (!engineUserOverride) {
        const rec =
          (data.engine_recommendation as EngineRecommendation | undefined) ||
          (builtPlan?.engine_recommendation as EngineRecommendation | undefined);
        const applied = applyEngineRecommendation(rec);
        if (applied) {
          setEngine(applied.engine);
          if (applied.sqlDialect) setSqlDialect(applied.sqlDialect);
        } else if (typeof data.recommended_codegen_engine === 'string') {
          setEngine(parseCodegenEngine(data.recommended_codegen_engine));
          if (data.recommended_sql_dialect === 'ansi' || data.recommended_sql_dialect === 'tsql') {
            setSqlDialect(data.recommended_sql_dialect);
          }
        }
      }
      setPlanValidationErrors(
        Array.isArray(data.plan_validation_errors) ? data.plan_validation_errors : []
      );
      setStep('plan');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Plan request failed');
    } finally {
      setBusy(false);
    }
  };

  const applyJsonPlan = () => {
    setErr(null);
    try {
      const parsed = JSON.parse(planJson) as Record<string, unknown>;
      if (!parsed.datasets || typeof parsed.datasets !== 'object') {
        setErr('Invalid plan: missing datasets object');
        return;
      }
      setPlan(parsed);
    } catch {
      setErr('Invalid JSON — fix syntax and try again');
    }
  };

  const removePlanRow = (id: string) => {
    if (!plan) return;
    const next = planRows.filter((r) => r.id !== id);
    setPlanRows(next);
    setPlan(rowsToPlan(plan, next));
  };

  const manualReviewItems = useMemo((): ManualReviewItem[] => {
    const raw = (plan as { manual_review?: unknown[] } | null)?.manual_review;
    if (!Array.isArray(raw)) return [];
    return raw.filter((m): m is ManualReviewItem => typeof m === 'object' && m !== null && 'id' in m);
  }, [plan]);

  useEffect(() => {
    setManualReviewItemsState(manualReviewItems);
  }, [manualReviewItems]);

  const pendingManualCount = useMemo(
    () => manualReviewItemsState.filter((m) => !m.default_resolution).length,
    [manualReviewItemsState]
  );

  const planApproveReady = useMemo(() => {
    if (!plan) return false;
    if (Array.isArray(plan.blocked) && (plan.blocked as unknown[]).length > 0) return false;
    if (pendingManualCount > 0) return false;
    const dsPlan = (plan.datasets || {}) as Record<
      string,
      { steps?: Array<{ classification?: string; bucket?: string; requires_user_choice?: boolean }> }
    >;
    for (const block of Object.values(dsPlan)) {
      for (const st of block.steps || []) {
        const cls = String(st.classification || st.bucket || 'auto').toLowerCase();
        if (cls === 'blocked') return false;
        if (cls === 'review' && st.requires_user_choice) return false;
      }
    }
    return true;
  }, [plan, pendingManualCount]);

  const applyManualResolutions = async (
    resolutions: Array<{ item_id: string; resolution_id: string }>
  ) => {
    setBusy(true);
    setErr(null);
    let bodyPlan: Record<string, unknown> | undefined = plan ?? undefined;
    if (planTab === 'json' && planJson) {
      try {
        bodyPlan = JSON.parse(planJson) as Record<string, unknown>;
      } catch {
        setErr('Invalid plan JSON — fix or switch to table view');
        setBusy(false);
        return;
      }
    }
    try {
      const res = await fetch('/api/etl/apply-manual-resolutions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          plan: bodyPlan,
          resolutions,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok && !data?.plan) {
        setErr(data?.message || data?.error || `Apply resolutions failed (${res.status})`);
        return;
      }
      if (data?.plan) setPlan(data.plan as Record<string, unknown>);
      setPlanValidationErrors(
        Array.isArray(data?.plan_validation_errors) ? data.plan_validation_errors : []
      );
      if (data?.pending_manual_review > 0) {
        setErr(
          data?.message ||
            `${data.pending_manual_review} manual review item(s) still pending — resolve all before confirm.`
        );
      } else if (Array.isArray(data?.errors) && data.errors.length > 0) {
        setErr(data.errors.join(' | '));
      } else {
        setErr(null);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Apply resolutions failed');
    } finally {
      setBusy(false);
    }
  };

  const runConfirm = async () => {
    if (pendingManualCount > 0) {
      setErr(`Resolve ${pendingManualCount} manual review item(s) below before confirming.`);
      return;
    }
    setBusy(true);
    setErr(null);
    let bodyPlan: Record<string, unknown> | undefined = plan ?? undefined;
    if (planTab === 'json') {
      try {
        bodyPlan = JSON.parse(planJson) as Record<string, unknown>;
      } catch {
        setErr('Invalid plan JSON — fix or switch to table view');
        setBusy(false);
        return;
      }
    }
    try {
      const res = await fetch('/api/etl/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, plan: bodyPlan ?? undefined }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        const errs = data?.plan_validation_errors ?? data?.detail?.plan_validation_errors;
        if (Array.isArray(errs) && errs.length > 0) {
          setPlanValidationErrors(errs);
        }
        setErr(data?.message || data?.error || data?.detail?.message || `Confirm failed (${res.status})`);
        return;
      }
      setPreview((data.preview as Record<string, unknown>) || null);
      if (data.lineage) setLineage(data.lineage as Record<string, unknown>);
      if (data.approved_plan) setPlan(data.approved_plan as Record<string, unknown>);
      if (pipelineMode === 'requirements') {
        onContinueToEtlStep?.();
        return;
      }
      setStep('preview');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Confirm request failed');
    } finally {
      setBusy(false);
    }
  };

  const runGenerate = async () => {
    setBusy(true);
    setErr(null);
    const codegenMode = useAiCodegen ? 'llm_then_template' : 'template';
    setGenerateStatus(
      useAiCodegen
        ? 'Calling AI to generate code (may take 30–90 seconds)…'
        : 'Generating production template code (usually a few seconds)…'
    );
    try {
      const eng =
        engine === 'spark'
          ? 'pyspark'
          : engine === 'sql'
            ? sqlDialect === 'ansi'
              ? 'ansi'
              : 'sql'
            : engine;

      const isLocked = gateResult ? !gateResult.passed : false;
      const isPhase2Disabled = isLocked && !forceUnlock;

      // 1. Generate Phase 1 (Cleanse) Code
      const res1 = await fetch('/api/etl/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          engine: eng,
          sql_dialect: sqlDialect,
          codegen_mode: codegenMode,
          generation_mode: 'cleanse_only',
        }),
      });
      const data1 = await res1.json().catch(() => null);
      if (!res1.ok && !data1?.code) {
        throw new Error(data1?.message || `Phase 1 generation failed (${res1.status})`);
      }
      
      const p1 = String(data1?.code || '');
      setPhase1Code(p1);
      
      // Parse quality metrics from Phase 1
      const score = parseQualityScore(p1);
      setSqlQualityScore(score);

      // 2. Generate Phase 2 (Transform) Code (if full mode and not gated/locked)
      let p2 = null;
      if (generationMode === 'full' && !isPhase2Disabled) {
        const res2 = await fetch('/api/etl/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            engine: eng,
            sql_dialect: sqlDialect,
            codegen_mode: codegenMode,
            generation_mode: 'transform_only',
          }),
        });
        const data2 = await res2.json().catch(() => null);
        if (res2.ok && data2?.code) {
          p2 = String(data2.code);
        }
      }
      setPhase2Code(p2);

      // Combine both or set active code tab
      onCodeGenerated?.(p1);
      setValidationOk(Boolean(data1?.validation_ok));
      setValidationErrors(Array.isArray(data1?.validation_errors) ? data1.validation_errors : []);
      setArtifactPath(typeof data1?.artifact_rel_path === 'string' ? data1.artifact_rel_path : null);
      setGeneratedBy(typeof data1?.generated_by === 'string' ? data1.generated_by : null);
      setIsDraft(Boolean(data1?.is_draft ?? !data1?.validation_ok));
      
      if (typeof data1?.latency_ms === 'number') {
        setGenerateStatus(
          `Done in ${(data1.latency_ms / 1000).toFixed(1)}s via ${data1.codegen_mode || data1.generated_by || 'template'}`
        );
      }
      setStep('code');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Generate request failed');
    } finally {
      setBusy(false);
    }
  };

  const copyCode = useCallback((text: string) => {
    if (!text.trim()) return;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const downloadCode = useCallback((text: string, type: 'phase1' | 'phase2') => {
    if (!text.trim()) return;
    const ext = engine === 'sql' ? 'sql' : engine === 'adf' ? 'json' : 'py';
    const name = `dhara_etl_${type}_${sessionId}.${ext}`;
    const mime = ext === 'json' ? 'application/json;charset=utf-8' : 'text/plain;charset=utf-8';
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }, [engine, sessionId]);

  const genLabel =
    engine === 'python'
      ? 'Python (pandas)'
      : engine === 'sql'
        ? `SQL (${sqlDialect})`
        : engine === 'spark'
          ? 'PySpark'
          : 'ADF JSON';

  if (!assessment && pipelineMode !== 'etl') return null;

  if (pipelineMode === 'etl' && etlSessionLoading) {
    return (
      <div className={shell}>
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#0070AD] text-white shadow-md">
            <FaCode className="text-lg" />
          </div>
          <div>
            <h3 className={`text-lg font-black tracking-tight ${dm ? 'text-white' : 'text-zinc-900'}`}>ETL preview & code</h3>
            <p className={`text-[12.5px] font-medium ${sub}`}>Loading saved plan and preview…</p>
          </div>
        </div>
      </div>
    );
  }

  const heading =
    pipelineMode === 'requirements'
      ? 'ETL rules & plan'
      : pipelineMode === 'etl'
        ? 'ETL preview & code'
        : 'ETL code generation';

  const flowSubtitle =
    pipelineMode === 'requirements'
      ? 'Target engine, column rules, and notes → editable plan'
      : pipelineMode === 'etl'
        ? `Impact preview → generate ${genLabel}`
        : `Business rules → plan (edit) → impact preview → ${genLabel}`;

  const confirmPlanLabel =
    pipelineMode === 'requirements' ? 'Save plan & go to ETL code' : 'Agree & preview impact';

  const { engineRecommendation, narration: planNarration, relationships: planRelationships } =
    getPlanFromRecord(plan);

  const useRecommendedEngine = () => {
    const applied = applyEngineRecommendation(engineRecommendation);
    if (applied) {
      setEngineUserOverride(false);
      setEngine(applied.engine);
      if (applied.sqlDialect) setSqlDialect(applied.sqlDialect);
    }
  };

  const getStepMeta = (dataset: string, order: number) => {
    const dsBlock = (plan?.datasets as Record<string, { steps?: Record<string, unknown>[] }> | undefined)?.[
      dataset
    ];
    return (dsBlock?.steps || []).find((s) => Number(s.order) === order);
  };

  const datasetNames = Object.keys(assessment?.datasets || {});

  // Preflight validation object
  const preflightValidation: ValidationResult = {
    success: planValidationErrors.length === 0 && pendingManualCount === 0,
    checks: [
      {
        id: 'req_cols',
        label: 'Required Columns Presence Check',
        status: requiredColumns ? 'success' : 'warning',
        message: requiredColumns ? 'Target required columns defined' : 'No strict required columns listed',
      },
      {
        id: 'never_drop',
        label: 'Never Drop Rows Safety Check',
        status: 'success',
        message: neverDropRows ? 'Preferring null fills to avoid losing counts' : 'Row dropping allowed for outliers/keys',
      },
      {
        id: 'manual_reviews',
        label: 'Manual Review Decisions',
        status: pendingManualCount > 0 ? 'warning' : 'success',
        message: pendingManualCount > 0 ? `${pendingManualCount} decisions need resolution` : 'All manual exceptions handled',
      },
      {
        id: 'dq_gate_overall',
        label: 'Overall Quality Gating Status',
        status: gateResult?.passed ? 'success' : 'warning',
        message: gateResult?.passed ? 'Datasets pass quality threshold' : 'Some datasets locked for Phase 2 transforms',
      }
    ]
  };

  return (
    <div className={shell}>
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#0070AD] text-white shadow-md">
          <FaCode className="text-lg" />
        </div>
        <div>
          <h3 className={`text-lg font-black tracking-tight ${dm ? 'text-white' : 'text-zinc-900'}`}>{heading}</h3>
          <p className={`text-[12.5px] font-medium ${sub}`}>{flowSubtitle}</p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest">
        {stepBadges.map((s) => (
          <span
            key={s}
            className={`rounded-full px-3 py-1 ${
              step === s
                ? 'bg-[#0070AD] text-white'
                : dm
                  ? 'bg-white/10 text-white/50'
                  : 'bg-black/5 text-black/40'
            }`}
          >
            {badgeLabel(s)}
          </span>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {(pipelineMode === 'full' || pipelineMode === 'requirements') && step === 'rules' && (
          <motion.div
            key="rules"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="space-y-6"
          >
            {/* Sub-panel A: Generation Mode Selector */}
            <GenerationModeSelector
              generationMode={generationMode}
              onChange={setGenerationMode}
              gateResult={gateResult}
              forceUnlock={forceUnlock}
              onForceUnlockChange={setForceUnlock}
            />

            {/* Target Engine & Location configurations */}
            <div className="rounded-2xl border border-black/10 bg-white/60 p-6 shadow-sm space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className={`mb-1.5 text-[11px] font-black uppercase tracking-widest ${label}`}>Target engine</div>
                  <div className="flex flex-wrap gap-2">
                    {(
                      [
                        ['python', 'Python'],
                        ['sql', 'SQL'],
                        ['spark', 'PySpark'],
                        ['adf', 'ADF'],
                      ] as const
                    ).map(([k, lab]) => (
                      <button
                        key={k}
                        type="button"
                        onClick={() => {
                          setEngineUserOverride(true);
                          setEngine(k);
                        }}
                        className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
                          engine === k
                            ? 'bg-[#0070AD] text-white'
                            : dm
                              ? 'bg-white/10 text-white/80'
                              : 'bg-black/5 hover:bg-black/10 text-zinc-700'
                        }`}
                      >
                        {lab}
                      </button>
                    ))}
                  </div>
                </div>
                {engine === 'sql' ? (
                  <div>
                    <div className={`mb-1.5 text-[11px] font-black uppercase tracking-widest ${label}`}>SQL dialect</div>
                    <select
                      value={sqlDialect}
                      onChange={(e) => setSqlDialect(e.target.value as 'tsql' | 'ansi')}
                      className={field}
                    >
                      <option value="tsql">T-SQL (Azure SQL / SQL Server)</option>
                      <option value="ansi">ANSI (portable comments / casts)</option>
                    </select>
                  </div>
                ) : null}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className={`mb-1.5 text-[11px] font-black uppercase tracking-widest ${label}`}>
                    Rule set (tenant)
                  </div>
                  <select value={tenantId} onChange={(e) => setTenantId(e.target.value)} className={field}>
                    {tenantOptions.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <div className={`mb-1.5 text-[11px] font-black uppercase tracking-widest ${label}`}>
                    Output destination
                  </div>
                  <select
                    value={targetDestination}
                    onChange={(e) =>
                      setTargetDestination(e.target.value as 'dataframe_only' | 'new_path' | 'overwrite')
                    }
                    className={field}
                  >
                    <option value="dataframe_only">Return DataFrame only (notebook / library use)</option>
                    <option value="new_path">Write to new path</option>
                    <option value="overwrite">Overwrite source (in-place)</option>
                  </select>
                  {targetDestination === 'new_path' ? (
                    <input
                      type="text"
                      value={targetPath}
                      onChange={(e) => setTargetPath(e.target.value)}
                      placeholder="cleaned/"
                      className={`mt-2 w-full ${field}`}
                    />
                  ) : null}
                </div>
              </div>
            </div>

            {/* Sub-panel B: Business Rules Form per dataset */}
            <div className="space-y-6">
              {datasetNames.map((dsName) => (
                <RequirementsPhasePanel
                  key={dsName}
                  datasetName={dsName}
                  gateResult={gateResult}
                  threshold={dqThreshold}
                  generationMode={generationMode}
                  forceUnlock={forceUnlock}
                  
                  neverDropRows={neverDropRows}
                  onNeverDropRowsChange={setNeverDropRows}
                  requiredColumns={requiredColumns}
                  onRequiredColumnsChange={setRequiredColumns}
                  excludeColumns={excludeColumns}
                  onExcludeColumnsChange={setExcludeColumns}
                  outlierStrategy={outlierStrategy}
                  onOutlierStrategyChange={setOutlierStrategy}
                  
                  notes={notes}
                  onNotesChange={setNotes}
                  scdType={scdType}
                  onScdTypeChange={setScdType}
                  hashPhone={hashPhone}
                  onHashPhoneChange={setHashPhone}
                  maskEmail={maskEmail}
                  onMaskEmailChange={setMaskEmail}
                />
              ))}
            </div>

            {/* Sub-panel C: Preflight Requirement Validator Checklist */}
            <RequirementValidator
              validation={preflightValidation}
              onGenerate={runPlan}
              busy={busy}
            />
          </motion.div>
        )}

        {(pipelineMode === 'full' || pipelineMode === 'requirements') && step === 'plan' && plan && (
          <motion.div
            key="plan"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="space-y-3"
          >
            <p className={`text-sm ${dm ? 'text-zinc-300' : 'text-black/60'}`}>
              Edit steps in the table, or switch to JSON. Confirm to run impact preview before code generation.
            </p>
            {engineRecommendation ? (
              <EngineRecommendationCard
                rec={engineRecommendation}
                narration={planNarration?.engine_explanation}
                darkMode={dm}
                currentEngine={engine}
                onUseRecommendation={useRecommendedEngine}
              />
            ) : null}
            <OverallReadinessBanner narration={planNarration || null} plan={plan} darkMode={dm} />
            <ManualReviewPanel
              items={manualReviewItemsState}
              darkMode={dm}
              busy={busy}
              onApply={applyManualResolutions}
            />
            <RelationshipsCard relationships={planRelationships} darkMode={dm} />
            <ManyToManyCard
              relationships={planRelationships}
              narration={planNarration?.relationships_summary}
              darkMode={dm}
            />
            {planValidationErrors.length > 0 ? (
              <div
                className={`rounded-xl border px-3 py-2 text-[12px] ${
                  dm ? 'border-amber-400/40 bg-amber-500/10 text-amber-100' : 'border-amber-200 bg-amber-50 text-amber-950'
                }`}
              >
                <strong>Plan validation notes</strong>
                <ul className="mt-1 list-disc pl-4">
                  {planValidationErrors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPlanTab('table')}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition-all ${planTab === 'table' ? 'bg-[#0070AD] text-white' : dm ? 'bg-white/10' : 'bg-black/5'}`}
              >
                Table
              </button>
              <button
                type="button"
                onClick={() => setPlanTab('json')}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition-all ${planTab === 'json' ? 'bg-[#0070AD] text-white' : dm ? 'bg-white/10' : 'bg-black/5'}`}
              >
                JSON
              </button>
            </div>

            {planTab === 'table' ? (
              <div className="space-y-2">
                {planRows.length === 0 ? (
                  <div
                    className={`rounded-xl border px-3 py-2 text-[12px] leading-relaxed ${
                      dm ? 'border-amber-400/30 bg-amber-500/10 text-amber-100' : 'border-amber-200 bg-amber-50 text-amber-950'
                    }`}
                  >
                    <strong>No automatic steps yet</strong> — use the{' '}
                    <strong>Manual review</strong> panel above to pick how Dhara should handle each flagged exception.
                  </div>
                ) : null}
                <div className={`max-h-64 overflow-auto rounded-xl border ${dm ? 'border-white/10' : 'border-black/10'}`}>
                <table className="w-full text-left text-[11px]">
                  <thead className={dm ? 'bg-white/10' : 'bg-black/[0.04]'}>
                    <tr>
                      <th className="p-2 font-black uppercase tracking-tighter">Ds</th>
                      <th className="p-2 font-black uppercase tracking-tighter">#</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Col</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Action</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Type</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Why</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Risk</th>
                      <th className="p-2 font-black uppercase tracking-tighter">Rows</th>
                      <th className="p-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {planRows.map((r) => {
                      const stMeta = getStepMeta(r.dataset, r.order);
                      const evProfile = stMeta?.evidence_profile as StepEvidence | undefined;
                      const evText =
                        typeof stMeta?.evidence === 'string'
                          ? stMeta.evidence
                          : (stMeta?.reason as string | undefined);
                      const risk = String(stMeta?.risk || 'medium');
                      const rowImpact = String(stMeta?.row_impact || 'none');
                      return (
                      <tr key={r.id} className={dm ? 'border-t border-white/5' : 'border-t border-black/5'}>
                        <td className="p-2 font-mono">{r.dataset}</td>
                        <td className="p-2">{r.order}</td>
                        <td className="p-2 font-mono">{r.column ?? '—'}</td>
                        <td className="p-2 font-mono">{r.action}</td>
                        <td className="p-2">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[9px] font-black uppercase ${bucketBadgeClass(r.bucket, dm)}`}
                          >
                            {r.bucket || 'auto'}
                          </span>
                        </td>
                        <td className="p-2 max-w-[140px]">
                          <span className={`line-clamp-2 text-[10px] ${dm ? 'text-zinc-300' : 'text-zinc-700'}`}>
                            {(stMeta?.reason as string) || evText || '—'}
                          </span>
                          {evProfile || evText ? (
                            <StepEvidenceTooltip
                              evidence={
                                evProfile ||
                                ({
                                  why_this_action: evText || String(stMeta?.reason || ''),
                                } as StepEvidence)
                              }
                              bucket={r.bucket || 'auto'}
                              darkMode={dm}
                              narration={getStepNarration(plan, r.dataset, r.order)}
                            />
                          ) : null}
                        </td>
                        <td className="p-2">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[9px] font-black uppercase ${
                              risk === 'high'
                                ? dm
                                  ? 'bg-rose-500/30 text-rose-100'
                                  : 'bg-rose-100 text-rose-900'
                                : risk === 'low'
                                  ? dm
                                    ? 'bg-emerald-500/25 text-emerald-100'
                                    : 'bg-emerald-100 text-emerald-800'
                                  : dm
                                    ? 'bg-amber-500/30 text-amber-100'
                                    : 'bg-amber-100 text-amber-900'
                            }`}
                          >
                            {risk}
                          </span>
                        </td>
                        <td className="p-2 font-mono text-[10px]">{rowImpact}</td>
                        <td className="p-2 text-right">
                          <button
                            type="button"
                            title="Remove step"
                            onClick={() => removePlanRow(r.id)}
                            className="rounded p-1 text-rose-500 hover:bg-rose-500/10"
                          >
                            <FaTrash className="text-xs" />
                          </button>
                        </td>
                      </tr>
                    );
                    })}
                  </tbody>
                </table>
                </div>
              </div>
            ) : (
              <textarea
                value={planJson}
                onChange={(e) => setPlanJson(e.target.value)}
                rows={14}
                className={`w-full font-mono text-[11px] ${field}`}
              />
            )}

            <div className="flex flex-wrap gap-2 pt-2">
              {planTab === 'json' ? (
                <button
                  type="button"
                  onClick={() => applyJsonPlan()}
                  className={`rounded-xl px-4 py-2 text-sm font-semibold ${dm ? 'bg-white/15 text-white' : 'border border-black/10 bg-white text-zinc-800'}`}
                >
                  Apply JSON to plan
                </button>
              ) : null}
              <button
                type="button"
                disabled={busy}
                onClick={() => setStep('rules')}
                className={`rounded-xl px-4 py-2 text-sm font-semibold ${dm ? 'bg-white/10 text-white' : 'border border-black/10 bg-white text-zinc-800'}`}
              >
                Back
              </button>
              <button
                type="button"
                disabled={busy || !planApproveReady}
                title={
                  !planApproveReady
                    ? pendingManualCount > 0
                      ? `Resolve ${pendingManualCount} manual review item(s) first`
                      : 'Resolve blocked or review steps before approving'
                    : undefined
                }
                onClick={() => void runConfirm()}
                className="inline-flex items-center gap-2 rounded-xl bg-[#0070AD] px-4 py-2 text-sm font-bold text-white shadow hover:bg-[#0070AD]/90 disabled:opacity-50"
              >
                {planApproveReady ? 'Approve & preview impact' : confirmPlanLabel}
                {pendingManualCount > 0 ? ` (${pendingManualCount} review pending)` : null}{' '}
                <FaChevronRight className="text-xs" />
              </button>
            </div>
          </motion.div>
        )}

        {(pipelineMode === 'full' || pipelineMode === 'etl') && step === 'preview' && preview && (
          <motion.div
            key="preview"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="space-y-4"
          >
            {engineRecommendation ? (
              <EngineRecommendationCard
                rec={engineRecommendation}
                narration={planNarration?.engine_explanation}
                darkMode={dm}
                currentEngine={engine}
                onUseRecommendation={useRecommendedEngine}
              />
            ) : null}
            <OverallReadinessBanner narration={planNarration || null} plan={plan} darkMode={dm} />
            <RelationshipsCard relationships={planRelationships} darkMode={dm} />
            <ManyToManyCard
              relationships={planRelationships}
              narration={planNarration?.relationships_summary}
              darkMode={dm}
            />
            <p className={`text-sm font-bold ${dm ? 'text-white' : 'text-zinc-900'}`}>
              Expected impact (DQ counts + column profile heuristics)
            </p>
            <ul className={`list-disc space-y-1 pl-5 text-sm ${dm ? 'text-zinc-200' : 'text-zinc-800'}`}>
              {(Array.isArray(preview.summary_lines) ? preview.summary_lines : []).map((line: string, i: number) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
            <EtlLineageVisualizer lineage={lineage as LineageMap} darkMode={dm} />
            <label
              className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-3 text-xs ${
                dm ? 'border-white/10 bg-black/20' : 'border-black/10 bg-white'
              }`}
            >
              <input
                type="checkbox"
                checked={useAiCodegen}
                onChange={(e) => setUseAiCodegen(e.target.checked)}
                disabled={busy}
                className="mt-0.5"
              />
              <span className={dm ? 'text-zinc-200' : 'text-zinc-800'}>
                <span className="font-semibold">Enhance with AI</span> (slower — calls Azure OpenAI, 30–90s).
                Leave unchecked for fast template code from your plan (recommended).
              </span>
            </label>
            {busy && generateStatus ? (
              <p
                className={`text-xs font-medium text-emerald-600`}
                role="status"
              >
                {generateStatus}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  pipelineMode === 'etl' && onEditPlanInRequirements
                    ? onEditPlanInRequirements()
                    : setStep('plan')
                }
                className={`rounded-xl px-4 py-2 text-sm font-semibold ${dm ? 'bg-white/10 text-white' : 'border border-black/10 bg-white text-zinc-800'}`}
              >
                {pipelineMode === 'etl' && onEditPlanInRequirements ? 'Edit plan in Requirements' : 'Back to plan'}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void runGenerate()}
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {busy
                  ? useAiCodegen
                    ? 'Generating with AI…'
                    : 'Generating…'
                  : `Generate ${genLabel}`}{' '}
                <FaChevronRight className="text-xs" />
              </button>
            </div>
          </motion.div>
        )}

        {(pipelineMode === 'full' || pipelineMode === 'etl') && step === 'code' && (
          <motion.div
            key="code"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="space-y-4"
          >
            {/* Dynamic tabs for Cleanse, Transform and Manual exceptions */}
            <ETLCodeTabView
              activeTab={activeCodeTab}
              onTabChange={setActiveCodeTab}
              phase1Code={phase1Code}
              phase2Code={phase2Code}
              manualItems={manualReviewItemsState}
              gateResult={gateResult}
              qualityScore={sqlQualityScore}
              onResolveItem={(itemId, resId) => applyManualResolutions([{ item_id: itemId, resolution_id: resId }])}
              onSkipItem={(itemId) => applyManualResolutions([{ item_id: itemId, resolution_id: 'skip' }])}
              onCopy={copyCode}
              onDownload={downloadCode}
              onForceUnlock={() => setForceUnlock(true)}
            />

            <div className="flex flex-wrap gap-2 pt-2">
              <button
                type="button"
                onClick={() => {
                  if (pipelineMode === 'etl' && onEditPlanInRequirements) {
                    onEditPlanInRequirements();
                    return;
                  }
                  setStep('rules');
                  setPlan(null);
                  setPreview(null);
                  setPhase1Code(null);
                  setPhase2Code(null);
                  setValidationOk(null);
                  setValidationErrors([]);
                  setArtifactPath(null);
                  setPlanJson('');
                  setPlanRows([]);
                  setSqlQualityScore(null);
                }}
                className={`rounded-xl px-4 py-2 text-sm font-semibold ${dm ? 'bg-white/10 text-white' : 'border border-black/10 bg-white text-zinc-800'}`}
              >
                {pipelineMode === 'etl' && onEditPlanInRequirements ? 'Edit plan in Requirements' : 'Start over'}
              </button>
              {onContinueAfterCode && (phase1Code || phase2Code) ? (
                <button
                  type="button"
                  onClick={() => onContinueAfterCode()}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#0070AD] px-4 py-2 text-sm font-bold text-white shadow hover:bg-[#0070AD]/90"
                >
                  Continue to Deploy <FaChevronRight className="text-xs" />
                </button>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {err ? (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-red-300/50 bg-red-950/45 px-3 py-2 text-sm text-red-100">
          <FaExclamationTriangle className="mt-0.5 shrink-0" />
          <span>{err}</span>
        </div>
      ) : null}
    </div>
  );
}
