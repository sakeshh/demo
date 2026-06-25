'use client';

import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaDatabase, FaFileAlt, FaChartBar, FaCode, FaCheck, FaArrowLeft, FaDownload, FaEye, FaArrowRight, FaClipboardList, FaTags, FaExclamationTriangle, FaCheckCircle, FaCloudUploadAlt } from 'react-icons/fa';
import { useRouter } from 'next/navigation';
import AnimatedBackground from '@/components/AnimatedBackground';
import DatabaseSelector from '@/components/DatabaseSelector';
import FileSelector from '@/components/FileSelector';
import DataAssessmentReport from '@/components/DataAssessmentReport';
import EtlGenerationPanel from '@/components/EtlGenerationPanel';
import DataCleaner from '@/components/DataCleaner';
import Confetti from '@/components/Confetti';
import SemanticReviewPanel from '@/components/SemanticReviewPanel';
import DQGateDashboard from '@/components/DQGateDashboard';
import { DQGateResult } from '@/types/pipeline';
import BusinessRequirementsPanel from '@/components/BusinessRequirementsPanel';

interface ExecutionResult {
  ok: boolean;
  stage: string;
  run_id: string;
  requires_approval: boolean;
  ops_found: string[];
  dry_run: boolean;
  execution?: any;
  post_execution_summary?: {
    transaction_committed: boolean;
    total_rows_affected: number;
    total_duration_ms: number;
    batch_count: number;
    row_deltas?: Record<string, { before: number | null; after: number | null; delta: number | null }>;
    rollback_reason: string | null;
  };
  timestamp_utc: string;
  fabric_mirror_result?: any;
}

type Step = 'database' | 'files' | 'business-requirements' | 'assessment' | 'report' | 'semantics' | 'requirements' | 'etl' | 'cleaning' | 'complete';

function generateHtmlReportFromBackend(html: string): string {
  return html || '<!doctype html><html><head><meta charset="utf-8" /></head><body>No HTML report available.</body></html>';
}

function openHtmlReportInNewTab(html: string) {
  if (typeof window === 'undefined') return;
  const safeHtml = generateHtmlReportFromBackend(html);
  // Use a blob URL so large reports don't hit URL length limits.
  const blob = new Blob([safeHtml], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank', 'noopener,noreferrer');
  // Best-effort cleanup after the new tab has had time to load.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export default function DataPipelinePage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState<Step>('database');
  const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [availableFiles, setAvailableFiles] = useState<string[]>([]);
  const [assessmentData, setAssessmentData] = useState<any>(null);
  const [reportFormat, setReportFormat] = useState<string | null>(null);
  const [showReportView, setShowReportView] = useState(false);
  const [etlCode, setEtlCode] = useState<string | null>(null);
  const [includeTransformSuggestions, setIncludeTransformSuggestions] = useState<boolean>(true);
  const [includeDqRecommendations, setIncludeDqRecommendations] = useState<boolean>(true);
  const [etlSessionId, setEtlSessionId] = useState('default');
  const [approvedSemantics, setApprovedSemantics] = useState<Record<string, Record<string, string>> | null>(null);
  const [dqThreshold, setDqThreshold] = useState<number>(70);
  const [forceUnlock, setForceUnlock] = useState<boolean>(false);
  const [semanticOverrides, setSemanticOverrides] = useState<Record<string, any>>({});

  const [execResult, setExecResult] = useState<ExecutionResult | null>(null);
  const [execLoading, setExecLoading] = useState(false);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [executionError, setExecutionError] = useState<string | null>(null);

  async function handleExecuteSQL(approved = false) {
    setExecLoading(true);
    setExecutionError(null);
    try {
      const res = await fetch('/api/etl/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: etlSessionId,
          approved: approved,
          dry_run: dryRun,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || 'Execution failed');
      }
      if (data.stage === 'approval_required') {
        setApprovalRequired(true);
        setExecResult(data);
      } else {
        setExecResult(data);
        setApprovalRequired(false);
      }
    } catch (e: any) {
      setExecutionError(e.message || 'Execution failed');
    } finally {
      setExecLoading(false);
      setDryRun(false);
    }
  }

  // Memoized client-side DQ Gate calculation matching backend check_dq_gate
  const dqGate = useMemo<DQGateResult | null>(() => {
    if (!assessmentData) return null;
    
    const resultData = assessmentData.result ?? assessmentData;
    const datasets = resultData.datasets ?? {};
    const datasetNames = Object.keys(datasets);
    if (datasetNames.length === 0) return null;

    const datasetGateDetails: Record<string, {
      dq_score: number;
      grade: 'A' | 'B' | 'C' | 'F';
      phase2_allowed: boolean;
      reason: string;
    }> = {};
    
    let overallPassed = true;
    let overallScoreSum = 0;
    let hasHighPiiOverall = false;

    for (const dsName of datasetNames) {
      const dsInfo = datasets[dsName] || {};
      const columns = dsInfo.columns || {};

      // 1. Null Score (30%)
      let nullScore = 100.0;
      const colNames = Object.keys(columns);
      if (colNames.length > 0) {
        let nullPctSum = 0;
        for (const colName of colNames) {
          const col = columns[colName] || {};
          const nullPct = col.null_percentage ?? col.null_pct ?? 0.0;
          nullPctSum += nullPct;
        }
        const avgNull = nullPctSum / colNames.length;
        nullScore = Math.max(0.0, 100.0 * Math.pow(1.0 - avgNull, 2));
      }

      // 2. Type Mismatch / Format Score (30%)
      const dqIssues = [...((dsInfo.quality || {}).issues || [])];
      const legacyIssues = (resultData.data_quality_issues || {}).datasets?.[dsName]?.issues || [];
      dqIssues.push(...legacyIssues);

      let typeMismatches = 0;
      for (const issue of dqIssues) {
        const issueType = String(issue.type || '').trim().toLowerCase();
        if (['type_mismatch', 'invalid_date_format', 'invalid_email', 'invalid_phone'].includes(issueType)) {
          typeMismatches += 1;
        }
      }
      const typeScore = Math.max(0.0, 100.0 - typeMismatches * 10.0);

      // 3. Duplicate Score (20%)
      const llmDsHints = dsInfo.llm_hints || {};
      const dupInfo = llmDsHints.business_key_confirmation || {};
      let dupCount = typeof dupInfo === 'object' && dupInfo !== null ? (dupInfo.business_key_duplicate_count || 0) : 0;
      for (const issue of dqIssues) {
        const issueType = String(issue.type || '').trim().toLowerCase();
        if (issueType.includes('duplicate') || issueType.includes('dup')) {
          dupCount += 1;
        }
      }
      const dupScore = Math.max(0.0, 100.0 - dupCount * 5.0);

      // 4. Outlier Score (20%)
      let outliersCount = 0;
      for (const issue of dqIssues) {
        const issueType = String(issue.type || '').trim().toLowerCase();
        if (issueType.includes('outlier')) {
          outliersCount += 1;
        }
      }
      const outlierScore = Math.max(0.0, 100.0 - outliersCount * 10.0);

      // Estimated client-side weighted DQ Score
      const estimatedDqScore = 0.30 * nullScore + 0.30 * typeScore + 0.20 * dupScore + 0.20 * outlierScore;

      // Prefer backend-calculated score, fall back to estimated if not present
      const dqDsBlock = (resultData.data_quality_issues || {}).datasets?.[dsName] || {};
      const dsSummary = dqDsBlock.summary || {};
      const dqScore = dsSummary.dq_score_0_100 !== undefined ? Number(dsSummary.dq_score_0_100) : estimatedDqScore;

      // Check high PII
      let hasHighPii = false;
      for (const colName of colNames) {
        const col = columns[colName] || {};
        const overrideKey = `${dsName}.${colName}`;
        const over = semanticOverrides[overrideKey];
        const piiLevel = over ? over.pii_level : (col.pii_level || 'none');
        if (piiLevel === 'high') {
          hasHighPii = true;
        }
      }
      if (hasHighPii) {
        hasHighPiiOverall = true;
      }

      const effectiveThreshold = hasHighPii ? Math.min(dqThreshold + 15.0, 95.0) : dqThreshold;
      const passed = dqScore >= effectiveThreshold || forceUnlock;

      let grade: 'A' | 'B' | 'C' | 'F' = 'F';
      if (dqScore >= 90) grade = 'A';
      else if (dqScore >= 80) grade = 'B';
      else if (dqScore >= 70) grade = 'C';

      datasetGateDetails[dsName] = {
        dq_score: Math.round(dqScore * 100) / 100,
        grade,
        phase2_allowed: passed,
        reason: passed
          ? ''
          : `Dataset score (${Math.round(dqScore)}%) below effective threshold (${effectiveThreshold}%). Phase 2 transform requirements locked.`,
      };

      if (!passed) {
        overallPassed = false;
      }
      overallScoreSum += dqScore;
    }

    const avgOverallScore = overallScoreSum / datasetNames.length;

    return {
      passed: overallPassed,
      score: Math.round(avgOverallScore * 100) / 100,
      threshold: dqThreshold,
      force_unlocked: forceUnlock,
      has_high_pii: hasHighPiiOverall,
      details: {
        null_score: 0,
        type_score: 0,
        duplicate_score: 0,
        outlier_score: 0,
      },
      datasets: datasetGateDetails,
    };
  }, [assessmentData, dqThreshold, forceUnlock, semanticOverrides]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    setEtlSessionId(window.localStorage.getItem('dharaSessionId') || 'default');
  }, [assessmentData]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const activeEl = document.getElementById(`step-btn-${currentStep}`);
    if (activeEl) {
      activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [currentStep]);

  const [userFeedback, setUserFeedback] = useState<Array<{
    step: string;
    liked: boolean;
    comment?: string;
  }>>([]);

  const steps = [
    { id: 'database', label: 'Database', icon: FaDatabase },
    { id: 'files', label: 'Files', icon: FaFileAlt },
    { id: 'business-requirements', label: 'Business Requirements', icon: FaClipboardList },
    { id: 'assessment', label: 'Assessment', icon: FaChartBar },
    { id: 'report', label: 'DQ Gate & Report', icon: FaChartBar },
    { id: 'semantics', label: 'Semantics', icon: FaTags },
    { id: 'requirements', label: 'Requirements', icon: FaClipboardList },
    { id: 'etl', label: 'ETL Code', icon: FaCode },
    { id: 'cleaning', label: 'Data Cleaning', icon: FaCheck },
  ];

  const handleDatabaseSelect = (database: string) => {
    setSelectedDatabase(database);
    setDirection('forward');
    setCurrentStep('files');
  };

  const handleFilesSelect = (files: string[], available: string[]) => {
    setSelectedFiles(files);
    setAvailableFiles(available);
  };

  const handleStartSemantics = () => {
    setDirection('forward');
    setCurrentStep('semantics');
  };

  const handleSemanticsComplete = (semantics: Record<string, Record<string, string>>) => {
    setApprovedSemantics(semantics);
    setDirection('forward');
    setCurrentStep('requirements');
  };

  const handleStartBusinessRequirements = () => {
    setDirection('forward');
    setCurrentStep('business-requirements');
  };

  const handleStartAssessment = () => {
    setDirection('forward');
    setCurrentStep('assessment');
  };

  const handleAssessmentComplete = (data: any) => {
    setAssessmentData(data);
    // Stay on assessment step so user can review/toggle options,
    // then explicitly continue to the report step.
  };

  const handleReportFormatSelect = (format: string) => {
    setReportFormat(format);
  };

  const handleDownloadReport = () => {
    if (!assessmentData || !reportFormat) return;
    const backendResult = assessmentData?.result ?? assessmentData;
    const md = typeof assessmentData?.report_markdown === 'string' ? assessmentData.report_markdown : null;
    const html = typeof assessmentData?.report_html === 'string' ? assessmentData.report_html : null;

    const blob =
      reportFormat === 'JSON'
        ? new Blob([JSON.stringify(backendResult, null, 2)], { type: 'application/json' })
        : reportFormat === 'MD'
          ? new Blob([md ?? 'No markdown report available.'], { type: 'text/markdown' })
          : new Blob([generateHtmlReportFromBackend(html ?? '')], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `assessment-report.${reportFormat === 'JSON' ? 'json' : reportFormat === 'MD' ? 'md' : 'html'}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleProceedFromReport = () => {
    setShowReportView(false);
    setDirection('forward');
    setCurrentStep('semantics');
  };

  const handleETLGenerated = (code: string) => {
    setEtlCode(code);
  };

  const handleStartCleaning = () => {
    setDirection('forward');
    setCurrentStep('cleaning');
  };

  const handleFeedback = (step: string, liked: boolean, comment?: string) => {
    setUserFeedback([...userFeedback, { step, liked, comment }]);
    
    if (!liked) {
      console.log(`User disliked ${step}. Feedback:`, comment);
    }
  };

  const [direction, setDirection] = useState<'forward' | 'back'>('forward');
  const getCurrentStepIndex = () => steps.findIndex(s => s.id === currentStep);

  const goToStep = (stepId: Step) => {
    const currIdx = getCurrentStepIndex();
    const targetIdx = steps.findIndex(s => s.id === stepId);
    setDirection(targetIdx >= currIdx ? 'forward' : 'back');
    setCurrentStep(stepId);
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-transparent">
      <AnimatedBackground pauseTime={0} />

      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 border-b border-black/10 bg-white/75 backdrop-blur-sm"
      >
        <div className="w-full px-6 py-4 flex items-center justify-between">
          <motion.button
            whileHover={{ x: -4 }}
            onClick={() => router.push('/chat')}
            className="flex items-center gap-2 text-black/65 hover:text-black transition-colors"
          >
            <FaArrowLeft />
            <span>Back to Chat</span>
          </motion.button>
          <h1 className="text-2xl font-bold text-zinc-900">
            Data Pipeline Workflow
          </h1>
          <div className="w-20" />
        </div>
      </motion.div>

      {/* Main Layout Grid */}
      <div className="relative z-10 w-full px-6 pt-4 pb-0">
        <div className="flex flex-col lg:flex-row gap-8 items-start">
          {/* Left Sidebar: Vertical Stepper */}
          <div className="w-full lg:w-72 shrink-0 bg-white/70 backdrop-blur-xl rounded-2xl border border-black/10 p-6 shadow-[0_8px_32px_rgba(0,0,0,0.04)] overflow-y-auto h-[calc(100vh-85px)] options-scroll">
            <h2 className="text-xs font-bold uppercase tracking-wider text-black/45 mb-6 px-2">
              Pipeline Steps
            </h2>
            <div className="relative flex flex-col space-y-6">
              {steps.map((step, index) => {
                const Icon = step.icon;
                const isActive = currentStep === step.id;
                const isCompleted = index < getCurrentStepIndex();
                const isClickable = isActive || isCompleted;
                
                return (
                  <div key={step.id} id={`step-btn-${step.id}`} className="relative flex items-start">
                    {/* Vertical Connector Line with Down Arrow */}
                    {index < steps.length - 1 && (
                      <div className="absolute left-8 top-14 h-[40px] w-2 -translate-x-1/2 flex flex-col items-center z-0">
                        {/* Line */}
                        <div className="w-0.5 flex-1 bg-black/10 relative overflow-hidden rounded-full">
                          <motion.div
                            className="absolute top-0 left-0 w-full bg-[#0070AD] origin-top"
                            initial={{ scaleY: 0 }}
                            animate={{ scaleY: isCompleted ? 1 : 0 }}
                            transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
                            style={{ height: '100%', originY: 0 }}
                          />
                        </div>
                        {/* Down Arrow Head */}
                        <svg 
                          className={`w-2 h-2 -mt-[1px] ${isCompleted ? 'text-[#0070AD]' : 'text-black/20'} transition-colors duration-300`} 
                          fill="currentColor" 
                          viewBox="0 0 10 10"
                        >
                          <path d="M5 8L1 4h8z" />
                        </svg>
                      </div>
                    )}

                    <motion.button
                      type="button"
                      onClick={() => isClickable && goToStep(step.id as Step)}
                      disabled={!isClickable}
                      className={`flex items-center gap-4 focus:outline-none focus:ring-2 focus:ring-[#0070AD]/25 focus:ring-offset-2 focus:ring-offset-white rounded-xl p-2 w-full text-left transition-all duration-200 ${
                        isActive 
                          ? 'bg-[#0070AD]/5 border border-[#0070AD]/10' 
                          : 'border border-transparent hover:bg-black/[0.02]'
                      } ${!isClickable ? 'cursor-default opacity-50' : 'cursor-pointer'}`}
                    >
                      <motion.div
                        className={`w-12 h-12 rounded-full flex items-center justify-center shrink-0 z-10 ${
                          isActive
                            ? 'bg-[#0070AD] text-white shadow-[0_0_15px_rgba(0,112,173,0.3)]'
                            : isCompleted
                            ? 'bg-[#0070AD]/80 text-white hover:bg-[#0070AD]'
                            : 'bg-black/5 text-black/45'
                        }`}
                        animate={isActive ? { scale: [1, 1.05, 1] } : {}}
                        transition={{ duration: 0.5, repeat: isActive ? Infinity : 0, repeatDelay: 2 }}
                        whileHover={isClickable ? { scale: 1.05 } : {}}
                        whileTap={isClickable ? { scale: 0.98 } : {}}
                      >
                        <Icon className="text-lg" />
                      </motion.div>
                      <div className="flex flex-col">
                        <span className={`text-sm font-semibold transition-colors ${
                          isActive ? 'text-zinc-900 font-bold' : isCompleted ? 'text-[#0070AD]' : 'text-black/45'
                        }`}>
                          {step.label}
                        </span>
                        <span className="text-[10px] text-black/35 font-medium mt-0.5">
                          {isActive ? 'In Progress' : isCompleted ? 'Completed' : 'Pending'}
                        </span>
                      </div>
                    </motion.button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column: Content Area */}
          <div className="flex-1 w-full lg:max-w-[calc(100%-19rem)]">
            <AnimatePresence mode="wait">
              <motion.div
                key={currentStep}
                initial={{ opacity: 0, x: direction === 'forward' ? 60 : -60 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: direction === 'forward' ? -60 : 60 }}
                transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
                className="options-scroll rounded-2xl border border-black/10 bg-white/75 p-8 shadow-[0_30px_120px_rgba(0,0,0,0.12)] backdrop-blur-xl h-[calc(100vh-85px)] overflow-y-auto"
              >
            {currentStep === 'database' && (
              <DatabaseSelector onSelect={handleDatabaseSelect} onBack={() => router.push('/chat')} />
            )}

            {currentStep === 'files' && selectedDatabase && (
              <FileSelector
                database={selectedDatabase}
                onSelect={handleFilesSelect}
                onNext={handleStartBusinessRequirements}
                selectedFiles={selectedFiles}
              />
            )}

            {currentStep === 'business-requirements' && (
              <BusinessRequirementsPanel
                sessionId={etlSessionId}
                selectedDatabase={selectedDatabase!}
                selectedFiles={selectedFiles}
                onComplete={handleStartAssessment}
                onBack={() => {
                  setDirection('back');
                  setCurrentStep('files');
                }}
              />
            )}

            {currentStep === 'assessment' && (
              <div className="flex flex-col h-full min-h-[calc(100vh-149px)]">
                <div className="flex-1 min-h-0 overflow-y-auto pr-2">
                  <DataAssessmentReport
                    files={selectedFiles}
                    database={selectedDatabase!}
                    includeTransformSuggestions={includeTransformSuggestions}
                    onIncludeTransformSuggestionsChange={setIncludeTransformSuggestions}
                    includeDqRecommendations={includeDqRecommendations}
                    onIncludeDqRecommendationsChange={setIncludeDqRecommendations}
                    onComplete={handleAssessmentComplete}
                    onFeedback={(liked, comment) => handleFeedback('assessment', liked, comment)}
                    approvedSemantics={semanticOverrides || undefined}
                  />
                </div>
                {assessmentData && (
                  <div className="pt-6 shrink-0">
                    <motion.button
                      type="button"
                      onClick={() => {
                        setDirection('forward');
                        setCurrentStep('report');
                      }}
                      className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-xl border border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] font-semibold hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60 transition-colors"
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                    >
                      Continue to DQ Gate & Report
                    </motion.button>
                  </div>
                )}
              </div>
            )}

            {currentStep === 'report' && assessmentData && (
              <div className="flex flex-col h-full min-h-[calc(100vh-149px)]">
                <div className="flex-1 min-h-0 overflow-y-auto pr-2 space-y-6">
                  {/* DQ Gate Dashboard */}
                  <DQGateDashboard
                    gateResult={dqGate}
                    threshold={dqThreshold}
                    onThresholdChange={setDqThreshold}
                  />

                  {!showReportView ? (
                    <>
                      <h2 className="text-2xl font-bold text-zinc-900">Select Report Format</h2>
                      <p className="text-black/60">Choose a format for your data assessment report</p>
                      <div className="grid grid-cols-2 gap-4">
                        {['JSON', 'HTML', 'MD'].map((format) => (
                          <motion.button
                            key={format}
                            onClick={() => handleReportFormatSelect(format)}
                            className={`p-6 rounded-xl border transition-all duration-300 ${
                              reportFormat === format
                                ? 'border-[#0070AD]/60 bg-[#0070AD]/10 shadow-[0_0_30px_rgba(0,112,173,0.12)]'
                                : 'border-black/10 bg-white/85 hover:border-[#0070AD]/30 hover:bg-white'
                            }`}
                            whileHover={{ y: -2 }}
                            whileTap={{ scale: 0.98 }}
                          >
                            <div className="text-lg font-semibold text-zinc-900">{format}</div>
                          </motion.button>
                        ))}
                      </div>
                      {reportFormat && (
                        <div className="flex flex-wrap items-center gap-3">
                          <motion.button
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            onClick={() => {
                              if (reportFormat === 'HTML') {
                                const html = typeof assessmentData?.report_html === 'string' ? assessmentData.report_html : '';
                                openHtmlReportInNewTab(html);
                                return;
                              }
                              setShowReportView(true);
                            }}
                            className="flex items-center gap-3 px-6 py-3 rounded-xl border border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] font-semibold hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60 transition-colors"
                          >
                            <FaEye className="w-5 h-5" />
                            {reportFormat === 'HTML' ? 'Open HTML in new tab' : 'View Report'}
                          </motion.button>

                          {reportFormat === 'HTML' && (
                            <motion.button
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              onClick={handleDownloadReport}
                              className="flex items-center gap-3 px-6 py-3 rounded-xl border border-black/10 bg-white/85 text-zinc-900 font-semibold hover:bg-white hover:border-[#0070AD]/30 transition-colors"
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.98 }}
                            >
                              <FaDownload className="w-5 h-5 text-[#0070AD]" />
                              Download HTML
                            </motion.button>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <h2 className="text-2xl font-bold text-zinc-900">Data Assessment Report</h2>
                      <div className="options-scroll max-h-[70vh] rounded-xl border border-black/10 bg-white/90 p-4 overflow-y-auto">
                        {reportFormat === 'JSON' ? (
                          <pre className="text-sm text-zinc-900 whitespace-pre-wrap font-mono">
                            {JSON.stringify(assessmentData?.result ?? assessmentData, null, 2)}
                          </pre>
                        ) : reportFormat === 'MD' ? (
                          <pre className="text-sm text-zinc-900 whitespace-pre-wrap font-mono">
                            {typeof assessmentData?.report_markdown === 'string' ? assessmentData.report_markdown : 'No markdown report available.'}
                          </pre>
                        ) : (
                          <div className="text-sm text-black/70">
                            HTML report opens in a new tab. Use Download to save as HTML.
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {reportFormat && (
                  <div className="pt-6 shrink-0 flex gap-4">
                    {showReportView && (
                      <motion.button
                        onClick={handleDownloadReport}
                        className="flex items-center gap-2 px-6 py-3 rounded-xl border border-black/10 bg-white/85 text-zinc-900 font-medium hover:bg-white hover:border-[#0070AD]/30 transition-colors"
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                      >
                        <FaDownload className="w-4 h-4" />
                        Download
                      </motion.button>
                    )}
                    <motion.button
                      onClick={handleProceedFromReport}
                      className="flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl border border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] font-semibold hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60 transition-colors"
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                    >
                      Continue to Column Semantics
                      <FaArrowRight className="w-4 h-4" />
                    </motion.button>
                  </div>
                )}
              </div>
            )}

            {currentStep === 'semantics' && selectedDatabase && (
              <SemanticReviewPanel
                database={selectedDatabase}
                files={selectedFiles}
                assessment={assessmentData?.result ?? assessmentData}
                dqGate={dqGate}
                onComplete={handleSemanticsComplete}
                onBack={() => {
                  setDirection('back');
                  setCurrentStep('report');
                }}
              />
            )}

            {currentStep === 'requirements' && (
              <div className="space-y-6">
                {!assessmentData ? (
                  <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                    Complete assessment and report before defining ETL rules and plan.
                  </p>
                ) : (
                  <EtlGenerationPanel
                    sessionId={etlSessionId}
                    assessment={(assessmentData?.result ?? assessmentData) as Record<string, unknown>}
                    variant="pipeline"
                    pipelineMode="requirements"
                    gateResult={dqGate}
                    semanticOverrides={semanticOverrides}
                    onContinueToEtlStep={() => {
                      setDirection('forward');
                      setCurrentStep('etl');
                    }}
                  />
                )}
              </div>
            )}

            {currentStep === 'etl' && (
              <div className="space-y-4">
                {!assessmentData ? (
                  <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                    Complete earlier steps before generating ETL code.
                  </p>
                ) : (
                  <>
                    <EtlGenerationPanel
                      sessionId={etlSessionId}
                      assessment={(assessmentData?.result ?? assessmentData) as Record<string, unknown>}
                      variant="pipeline"
                      pipelineMode="etl"
                      gateResult={dqGate}
                      semanticOverrides={semanticOverrides}
                      onEditPlanInRequirements={() => {
                        setDirection('back');
                        setCurrentStep('requirements');
                      }}
                      onCodeGenerated={handleETLGenerated}
                      onContinueAfterCode={handleStartCleaning}
                    />

                    {/* SQL direct execution section */}
                    {etlCode && (
                      <div className="mt-6 border-t border-black/10 pt-6 space-y-6">
                        <h4 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
                          <FaDatabase className="text-[#0070AD]" />
                          Azure SQL Direct Execution
                        </h4>

                        <div className="flex flex-wrap gap-3">
                          <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            disabled={execLoading}
                            onClick={() => { setDryRun(false); handleExecuteSQL(false); }}
                            className="flex items-center gap-2 px-6 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-700 transition-colors disabled:opacity-50"
                          >
                            ▶ Execute in Azure SQL
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            disabled={execLoading}
                            onClick={() => { setDryRun(true); handleExecuteSQL(false); }}
                            className="flex items-center gap-2 px-6 py-3 rounded-xl border border-black/10 bg-white text-zinc-900 font-semibold hover:bg-zinc-50 hover:border-[#0070AD]/30 transition-colors disabled:opacity-50"
                          >
                            🔍 Dry Run
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            onClick={() => router.push('/execution-report')}
                            className="flex items-center gap-2 px-6 py-3 rounded-xl border border-dashed border-[#0070AD]/40 bg-[#0070AD]/5 text-[#0070AD] font-semibold hover:bg-[#0070AD]/10 transition-colors"
                          >
                            📋 View Execution Report
                          </motion.button>
                        </div>

                        {execLoading && (
                          <div className="flex items-center gap-2 text-sm text-[#0070AD] font-medium" role="status">
                            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                            </svg>
                            <span>Executing T-SQL batches on database...</span>
                          </div>
                        )}

                        {executionError && (
                          <div className="flex items-start gap-2 rounded-xl border border-red-300/50 bg-red-50 px-3 py-2 text-sm text-red-900">
                            <FaExclamationTriangle className="mt-0.5 shrink-0 text-red-600" />
                            <span>{executionError}</span>
                          </div>
                        )}

                        {/* Approval Gate */}
                        {approvalRequired && execResult && (
                          <div className="p-5 rounded-xl border border-amber-300 bg-amber-50 text-amber-950 space-y-3 shadow-sm">
                            <div className="flex items-center gap-2 font-bold">
                              <FaExclamationTriangle className="text-amber-600" />
                              <span>Destructive Operations Detected</span>
                            </div>
                            <p className="text-sm">
                              The SQL script contains statements that modify DB structure or delete data:
                            </p>
                            <ul className="list-disc pl-5 text-xs font-mono font-bold">
                              {execResult.ops_found?.map((op, idx) => (
                                <li key={idx}>{op}</li>
                              ))}
                            </ul>
                            <p className="text-xs text-black/60">
                              Please confirm you understand that these changes will be executed inside a database transaction.
                            </p>
                            <div className="flex gap-3">
                              <motion.button
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.98 }}
                                onClick={() => handleExecuteSQL(true)}
                                className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm transition-colors"
                              >
                                I understand, proceed
                              </motion.button>
                              <motion.button
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.98 }}
                                onClick={() => setApprovalRequired(false)}
                                className="px-4 py-2 rounded-lg border border-black/10 hover:bg-black/5 text-zinc-900 font-semibold text-sm transition-colors"
                              >
                                Cancel
                              </motion.button>
                            </div>
                          </div>
                        )}

                        {/* Execution Result Panel */}
                        {execResult && execResult.stage === 'execution' && (
                          <div className="p-6 rounded-2xl border border-black/10 bg-white/90 shadow-sm space-y-4">
                            <div className="flex items-center justify-between">
                              <h5 className="text-base font-bold text-zinc-900 flex items-center gap-2">
                                <FaClipboardList className="text-[#0070AD]" />
                                Execution Result
                              </h5>
                              <span className="text-xs text-black/45 font-mono">Run ID: {execResult.run_id}</span>
                            </div>

                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                              <div className="p-3 rounded-xl bg-black/[0.02] border border-black/5">
                                <div className="text-[10px] font-black uppercase tracking-wider text-black/45">Status</div>
                                <div className="mt-1">
                                  {execResult.post_execution_summary?.transaction_committed ? (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-800">
                                      <FaCheck className="text-[10px]" /> Committed
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-bold text-rose-800">
                                      <FaExclamationTriangle className="text-[10px]" /> Rolled Back
                                    </span>
                                  )}
                                </div>
                              </div>

                              <div className="p-3 rounded-xl bg-black/[0.02] border border-black/5">
                                <div className="text-[10px] font-black uppercase tracking-wider text-black/45">Rows Affected</div>
                                <div className="mt-1 text-base font-bold text-zinc-900">
                                  {execResult.post_execution_summary?.total_rows_affected ?? 0}
                                </div>
                              </div>

                              <div className="p-3 rounded-xl bg-black/[0.02] border border-black/5">
                                <div className="text-[10px] font-black uppercase tracking-wider text-black/45">Duration</div>
                                <div className="mt-1 text-base font-bold text-zinc-900">
                                  {execResult.post_execution_summary?.total_duration_ms?.toFixed(1) ?? 0} ms
                                </div>
                              </div>

                              <div className="p-3 rounded-xl bg-black/[0.02] border border-black/5">
                                <div className="text-[10px] font-black uppercase tracking-wider text-black/45">Timestamp (UTC)</div>
                                <div className="mt-1 text-xs font-bold text-zinc-900 truncate">
                                  {execResult.timestamp_utc ? new Date(execResult.timestamp_utc).toLocaleTimeString() : '—'}
                                </div>
                              </div>
                            </div>

                            {execResult.post_execution_summary?.rollback_reason && (
                              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-950 text-xs">
                                <strong>Rollback Reason:</strong> {execResult.post_execution_summary.rollback_reason}
                              </div>
                            )}

                            {/* Fabric Mirroring Status */}
                            {execResult.fabric_mirror_result && (
                              <div className="p-4 rounded-xl border border-black/10 bg-white/70 space-y-3">
                                <h6 className="text-xs font-black uppercase tracking-wider text-zinc-900 flex items-center gap-2">
                                  <FaCloudUploadAlt className="text-[#0070AD]" />
                                  Microsoft Fabric Lakehouse OneLake Mirror
                                </h6>
                                {execResult.fabric_mirror_result.ok ? (
                                  <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700">
                                    <FaCheckCircle className="text-emerald-500" />
                                    <span>Cleaned data was successfully uploaded and mirrored to Fabric OneLake!</span>
                                  </div>
                                ) : (
                                  <div className="space-y-1.5">
                                    <div className="flex items-center gap-2 text-xs font-semibold text-rose-700">
                                      <FaExclamationTriangle className="text-rose-500 text-xs" />
                                      <span>Fabric OneLake Mirroring failed or was skipped.</span>
                                    </div>
                                    {execResult.fabric_mirror_result.message && (
                                      <p className="text-[11px] text-rose-600/90 bg-rose-50/50 p-2 rounded-lg font-mono">
                                        {execResult.fabric_mirror_result.message}
                                      </p>
                                    )}
                                  </div>
                                )}
                                
                                {Array.isArray(execResult.fabric_mirror_result.details) && (
                                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                                    {execResult.fabric_mirror_result.details.map((detail: any, idx: number) => (
                                      <div key={idx} className={`flex flex-col gap-1 text-xs p-2.5 rounded-lg border ${detail.ok ? 'bg-black/[0.02] border-black/5' : 'bg-rose-50/60 border-rose-200/50'}`}>
                                        <div className="flex items-center justify-between">
                                          <span className="font-semibold text-zinc-700 font-mono truncate mr-2">{detail.table || detail.source || 'Unknown Table'}</span>
                                          {detail.ok ? (
                                            <span className="text-emerald-600 font-bold shrink-0 flex items-center gap-1">
                                              ✓ Ready ({detail.rows ?? 0} rows)
                                            </span>
                                          ) : (
                                            <span className="text-rose-600 font-bold shrink-0">
                                              ⚠️ Failed ({detail.error || 'Unknown Error'})
                                            </span>
                                          )}
                                        </div>
                                        {!detail.ok && detail.message && (
                                          <p className="text-[10px] text-rose-600/80 font-mono break-all leading-relaxed mt-0.5">{detail.message}</p>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}

                            {!execResult.fabric_mirror_result && !execResult.dry_run && (
                              <div className="p-4 rounded-xl border border-dashed border-black/10 bg-black/[0.01] text-xs text-black/50 select-none">
                                Microsoft Fabric mirroring is disabled or not configured in environment.
                              </div>
                            )}

                            {execResult.execution?.batch_results && (
                              <div className="mt-4">
                                <div className="text-xs font-bold text-zinc-800 mb-2">Batch Execution Breakdown</div>
                                <div className="overflow-hidden rounded-xl border border-black/10">
                                  <table className="w-full text-left text-xs text-zinc-800">
                                    <thead className="bg-black/[0.02]">
                                      <tr>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55">Batch #</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55">Rows Affected</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55">Duration</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55">Status</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {execResult.execution.batch_results.map((batch: any, idx: number) => (
                                        <tr key={idx} className="border-t border-black/5">
                                          <td className="p-2.5 font-mono">{idx + 1}</td>
                                          <td className="p-2.5">{batch.rows_affected}</td>
                                          <td className="p-2.5">{batch.duration_ms?.toFixed(1)} ms</td>
                                          <td className="p-2.5">
                                            {batch.error ? (
                                              <span className="text-rose-600 font-semibold truncate max-w-[200px] inline-block">{batch.error}</span>
                                            ) : (
                                              <span className="text-emerald-600 font-semibold">Success</span>
                                            )}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}

                            {/* Row counts reconciliation */}
                            {execResult.post_execution_summary?.row_deltas && Object.keys(execResult.post_execution_summary.row_deltas).length > 0 && (
                              <div className="mt-4">
                                <div className="text-xs font-bold text-zinc-800 mb-2">Row Count Reconciliation</div>
                                <div className="overflow-hidden rounded-xl border border-black/10">
                                  <table className="w-full text-left text-xs text-zinc-800">
                                    <thead className="bg-black/[0.02]">
                                      <tr>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55">Table Name</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55 text-right">Before Count</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55 text-right">After Count</th>
                                        <th className="p-2.5 font-bold uppercase tracking-wider text-black/55 text-right">Delta</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {Object.entries(execResult.post_execution_summary.row_deltas).map(([tbl, counts]: [string, any]) => (
                                        <tr key={tbl} className="border-t border-black/5">
                                          <td className="p-2.5 font-mono">{tbl}</td>
                                          <td className="p-2.5 text-right">{counts.before ?? '—'}</td>
                                          <td className="p-2.5 text-right">{counts.after ?? '—'}</td>
                                          <td className="p-2.5 text-right font-bold">
                                            {counts.delta !== null && counts.delta !== undefined ? (
                                              <span className={counts.delta > 0 ? 'text-emerald-600' : counts.delta < 0 ? 'text-rose-600' : 'text-zinc-500'}>
                                                {counts.delta > 0 ? `+${counts.delta}` : counts.delta}
                                              </span>
                                            ) : '—'}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}


            {currentStep === 'cleaning' && (
              <DataCleaner
                files={selectedFiles}
                etlCode={etlCode}
                assessmentData={assessmentData}
                userFeedback={userFeedback}
                onComplete={() => { setDirection('forward'); setCurrentStep('complete'); }}
                onFeedback={(liked, comment) => handleFeedback('cleaning', liked, comment)}
              />
            )}

            {currentStep === 'complete' && (
              <div className="relative text-center py-12 overflow-visible">
                <Confetti trigger />
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 200 }}
                  className="w-24 h-24 bg-[#0070AD] rounded-full flex items-center justify-center mx-auto mb-6 shadow-[0_0_40px_rgba(0,112,173,0.25)]"
                >
                  <FaCheck className="text-4xl text-white" />
                </motion.div>
                <h2 className="text-3xl font-bold text-zinc-900 mb-4">Pipeline Complete!</h2>
                <p className="text-black/60 mb-8">
                  Your data has been processed successfully.
                </p>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => {
                    setDirection('forward');
                    setCurrentStep('database');
                    setSelectedDatabase(null);
                    setSelectedFiles([]);
                    setAssessmentData(null);
                    setReportFormat(null);
                    setShowReportView(false);
                    setEtlCode(null);
                  }}
                  className="px-6 py-3 rounded-xl border border-[#0070AD]/40 bg-[#0070AD]/10 text-[#0070AD] font-semibold hover:bg-[#0070AD]/15 hover:border-[#0070AD]/60 transition-colors"
                >
                  Start New Pipeline
                </motion.button>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
