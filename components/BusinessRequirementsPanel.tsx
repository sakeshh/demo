'use client';

import { useState, useRef, DragEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaClipboardList, FaUpload, FaTrash, FaArrowRight, FaRobot, FaCheckCircle, FaSpinner, FaTimes } from 'react-icons/fa';

interface CustomAssertion {
  assertion: string;
  severity: string;
  message: string;
}

interface BusinessRules {
  never_drop_rows: boolean;
  dq_threshold: number;
  outlier_strategy: string;
  required_columns: string[];
  non_nullable: string[];
  exclude_columns: string[];
  valid_values: Record<string, string[]>;
  custom_assertions: CustomAssertion[];
  notes: string;
}

interface BusinessRequirementsPanelProps {
  sessionId: string;
  selectedDatabase: string;
  selectedFiles: string[];
  onComplete: () => void;
  onBack: () => void;
}

export default function BusinessRequirementsPanel({
  sessionId,
  selectedDatabase,
  selectedFiles,
  onComplete,
  onBack,
}: BusinessRequirementsPanelProps) {
  const [textInput, setTextInput] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Parsed rules state
  const [rules, setRules] = useState<BusinessRules | null>(null);

  // Custom addition states
  const [newRequiredCol, setNewRequiredCol] = useState('');
  const [newNonNullCol, setNewNonNullCol] = useState('');
  const [newExcludeCol, setNewExcludeCol] = useState('');
  const [newAssertion, setNewAssertion] = useState('');
  const [newAssertionMsg, setNewAssertionMsg] = useState('');
  const [newAssertionSeverity, setNewAssertionSeverity] = useState('medium');

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      const validExtensions = ['.pdf', '.docx', '.txt', '.md'];
      const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
      if (validExtensions.includes(ext)) {
        setUploadedFile(file);
        setError(null);
      } else {
        setError('Unsupported file format. Please upload PDF, Word (.docx), TXT, or Markdown (.md) documents.');
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFile(e.target.files[0]);
      setError(null);
    }
  };

  const clearFile = () => {
    setUploadedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleParse = async () => {
    if (!textInput.trim() && !uploadedFile) {
      setError('Please type business requirements or upload a document file to parse.');
      return;
    }

    setParsing(true);
    setError(null);
    setSuccessMsg(null);

    const formData = new FormData();
    formData.append('session_id', sessionId);
    if (textInput.trim()) {
      formData.append('text', textInput);
    }
    if (uploadedFile) {
      formData.append('file', uploadedFile);
    }

    try {
      const res = await fetch('/api/business-rules/parse', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        throw new Error(data?.message || 'Failed to parse business requirements.');
      }

      setRules(data.rules);
      setSuccessMsg('Business requirements successfully analyzed and rules extracted!');
    } catch (err: any) {
      setError(err?.message || 'An error occurred while communicating with the AI model.');
    } finally {
      setParsing(false);
    }
  };

  const handleSaveAndProceed = async () => {
    if (!rules) return;

    setSaving(true);
    setError(null);

    try {
      const res = await fetch('/api/session-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          context: {
            pending_business_rules: rules,
          },
        }),
      });

      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        throw new Error(data?.message || 'Failed to save rules to session context.');
      }

      onComplete();
    } catch (err: any) {
      setError(err?.message || 'Failed to save requirements. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true);
    setError(null);
    const defaultRules: BusinessRules = {
      never_drop_rows: false,
      dq_threshold: 70,
      outlier_strategy: 'none',
      required_columns: [],
      non_nullable: [],
      exclude_columns: [],
      valid_values: {},
      custom_assertions: [],
      notes: '',
    };
    try {
      const res = await fetch('/api/session-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          context: {
            pending_business_rules: defaultRules,
          },
        }),
      });

      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        throw new Error(data?.message || 'Failed to save empty rules to session context.');
      }

      onComplete();
    } catch (err: any) {
      setError(err?.message || 'Failed to skip requirements. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  // Rule editing functions
  const toggleNeverDrop = () => {
    if (!rules) return;
    setRules({ ...rules, never_drop_rows: !rules.never_drop_rows });
  };

  const handleThresholdChange = (val: number) => {
    if (!rules) return;
    setRules({ ...rules, dq_threshold: Math.max(0, Math.min(100, val)) });
  };

  const handleStrategyChange = (val: string) => {
    if (!rules) return;
    setRules({ ...rules, outlier_strategy: val });
  };

  const addRequiredCol = () => {
    if (!rules || !newRequiredCol.trim()) return;
    const required_columns = rules.required_columns || [];
    if (!required_columns.includes(newRequiredCol.trim())) {
      setRules({
        ...rules,
        required_columns: [...required_columns, newRequiredCol.trim()],
      });
    }
    setNewRequiredCol('');
  };

  const removeRequiredCol = (col: string) => {
    if (!rules) return;
    const required_columns = rules.required_columns || [];
    setRules({
      ...rules,
      required_columns: required_columns.filter((c) => c !== col),
    });
  };

  const addNonNullCol = () => {
    if (!rules || !newNonNullCol.trim()) return;
    const non_nullable = rules.non_nullable || [];
    if (!non_nullable.includes(newNonNullCol.trim())) {
      setRules({
        ...rules,
        non_nullable: [...non_nullable, newNonNullCol.trim()],
      });
    }
    setNewNonNullCol('');
  };

  const removeNonNullCol = (col: string) => {
    if (!rules) return;
    const non_nullable = rules.non_nullable || [];
    setRules({
      ...rules,
      non_nullable: non_nullable.filter((c) => c !== col),
    });
  };

  const addExcludeCol = () => {
    if (!rules || !newExcludeCol.trim()) return;
    const exclude_columns = rules.exclude_columns || [];
    if (!exclude_columns.includes(newExcludeCol.trim())) {
      setRules({
        ...rules,
        exclude_columns: [...exclude_columns, newExcludeCol.trim()],
      });
    }
    setNewExcludeCol('');
  };

  const removeExcludeCol = (col: string) => {
    if (!rules) return;
    const exclude_columns = rules.exclude_columns || [];
    setRules({
      ...rules,
      exclude_columns: exclude_columns.filter((c) => c !== col),
    });
  };

  const addAssertion = () => {
    if (!rules || !newAssertion.trim()) return;
    const custom_assertions = rules.custom_assertions || [];
    setRules({
      ...rules,
      custom_assertions: [
        ...custom_assertions,
        {
          assertion: newAssertion.trim(),
          severity: newAssertionSeverity,
          message: newAssertionMsg.trim() || `Must satisfy constraint: ${newAssertion.trim()}`,
        },
      ],
    });
    setNewAssertion('');
    setNewAssertionMsg('');
    setNewAssertionSeverity('medium');
  };

  const removeAssertion = (index: number) => {
    if (!rules) return;
    const custom_assertions = rules.custom_assertions || [];
    setRules({
      ...rules,
      custom_assertions: custom_assertions.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="flex flex-col h-full min-h-[calc(100vh-149px)] space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-3xl font-black text-zinc-900 tracking-tight flex items-center gap-2">
            <FaClipboardList className="text-[#0070AD]" />
            Business Requirements & Rules
          </h2>
          <p className="text-sm text-black/60 mt-1">
            Specify data rules or upload requirements documents. The AI agent will profile and assess the dataset against them.
          </p>
        </div>
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-semibold rounded-xl border border-black/10 bg-white/70 hover:bg-black/[0.02] transition-colors"
        >
          Back to Files
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        {/* Left Column: Requirements Input */}
        <div className="space-y-6 bg-white/50 backdrop-blur-xl p-6 rounded-2xl border border-black/10 shadow-[0_8px_32px_rgba(0,0,0,0.02)]">
          <div className="flex flex-col space-y-2">
            <label className="text-sm font-bold text-zinc-800">
              Type Business Requirements
            </label>
            <textarea
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder="E.g.,&#10;- Column 'Customer_ID' is required and must be non-nullable.&#10;- Email column must only end with @capgemini.com.&#10;- Ignore null values on OrderDate.&#10;- Price must be greater than 0."
              className="w-full h-44 rounded-xl border border-black/10 p-4 text-sm bg-white/80 focus:ring-2 focus:ring-[#0070AD]/25 focus:border-[#0070AD] focus:outline-none placeholder:text-black/35 shadow-sm resize-none font-medium text-zinc-900"
            />
          </div>

          <div className="flex flex-col space-y-2">
            <label className="text-sm font-bold text-zinc-800">
              Or Upload Requirements Document
            </label>
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-300 flex flex-col items-center justify-center space-y-3 ${
                dragActive
                  ? 'border-[#0070AD] bg-[#0070AD]/5 shadow-[0_0_15px_rgba(0,112,173,0.1)]'
                  : 'border-black/10 hover:border-[#0070AD]/50 hover:bg-white/80'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,.md"
                onChange={handleFileChange}
                className="hidden"
              />
              <FaUpload className={`text-2xl ${dragActive ? 'text-[#0070AD]' : 'text-black/35'}`} />
              <div className="text-xs text-black/60 font-semibold">
                Drag & Drop PDF, DOCX, TXT, or MD file here, or{' '}
                <span className="text-[#0070AD] underline">browse</span>
              </div>
              <span className="text-[10px] text-black/35">Max file size: 10MB</span>
            </div>

            {uploadedFile && (
              <div className="flex items-center justify-between bg-white/95 rounded-xl border border-black/10 px-4 py-2.5 shadow-sm">
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="p-2 bg-[#0070AD]/10 text-[#0070AD] rounded-lg text-xs font-black uppercase">
                    {uploadedFile.name.split('.').pop()}
                  </div>
                  <span className="text-xs font-bold text-zinc-800 truncate">
                    {uploadedFile.name}
                  </span>
                  <span className="text-[10px] text-black/35 shrink-0">
                    ({(uploadedFile.size / 1024).toFixed(1)} KB)
                  </span>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    clearFile();
                  }}
                  className="text-black/35 hover:text-red-500 p-1.5 transition-colors"
                >
                  <FaTrash className="text-xs" />
                </button>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-rose-50 px-4 py-3 text-xs font-bold text-rose-950 shadow-sm flex items-start gap-2">
              <span className="mt-0.5">⚠️</span>
              <span>{error}</span>
            </div>
          )}

          {successMsg && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-bold text-emerald-950 shadow-sm flex items-start gap-2">
              <FaCheckCircle className="text-emerald-600 mt-0.5 shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}

          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            disabled={parsing}
            onClick={handleParse}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-gradient-to-r from-[#0070AD] to-[#12ABDB] text-white font-bold hover:shadow-[0_0_20px_rgba(0,112,173,0.3)] transition-all disabled:opacity-50 text-sm"
          >
            {parsing ? (
              <>
                <FaSpinner className="animate-spin text-lg" />
                Analyzing Business Rules (LLM)…
              </>
            ) : (
              <>
                <FaRobot className="text-lg" />
                Extract Rules using AI Agent
              </>
            )}
          </motion.button>

          <div className="text-center pt-2">
            <button
              type="button"
              onClick={handleSkip}
              disabled={saving}
              className="text-xs text-black/45 hover:text-[#0070AD] hover:underline font-bold transition-all disabled:opacity-50"
            >
              Skip this step & proceed without rules
            </button>
          </div>
        </div>

        {/* Right Column: Rule Verification & Customization */}
        <div className="space-y-6">
          {!rules ? (
            <div className="border border-dashed border-black/10 rounded-2xl p-12 text-center text-black/45 bg-white/30 backdrop-blur-xl h-[420px] flex flex-col items-center justify-center space-y-4">
              <FaClipboardList className="text-4xl text-black/25" />
              <h3 className="font-bold text-zinc-700">No Rules Extracted</h3>
              <p className="text-xs max-w-xs leading-relaxed">
                Provide business requirements on the left, then click <strong>Extract Rules</strong> to view, modify, and confirm constraints.
              </p>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSkip}
                  disabled={saving}
                  className="px-5 py-2.5 text-xs font-bold rounded-xl border border-black/10 bg-white/80 hover:bg-black/[0.02] hover:border-[#0070AD]/30 text-zinc-700 transition-all flex items-center gap-2 justify-center mx-auto shadow-sm disabled:opacity-50"
                >
                  {saving && <FaSpinner className="animate-spin text-[#0070AD]" />}
                  Skip & Proceed without Rules
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6 bg-white/70 backdrop-blur-xl p-6 rounded-2xl border border-black/10 shadow-[0_8px_32px_rgba(0,0,0,0.03)] max-h-[70vh] overflow-y-auto options-scroll">
              <div className="border-b border-black/10 pb-4 mb-4">
                <h3 className="text-base font-bold text-zinc-900">Extracted Rules Checklist</h3>
                <p className="text-xs text-black/50">Verify and customize the rules before running the scorecard check.</p>
              </div>

              {/* Global Switches */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="border border-black/5 rounded-xl p-3.5 bg-white/80 shadow-sm flex items-center justify-between">
                  <div>
                    <div className="text-xs font-bold text-zinc-800">Never Drop Rows</div>
                    <div className="text-[10px] text-black/45">Strict check: no rows deleted</div>
                  </div>
                  <button
                    onClick={toggleNeverDrop}
                    className={`px-3 py-1 text-xs font-bold rounded-lg transition-colors ${
                      rules.never_drop_rows
                        ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                        : 'bg-black/5 text-black/50 border border-black/10'
                    }`}
                  >
                    {rules.never_drop_rows ? 'ON' : 'OFF'}
                  </button>
                </div>

                <div className="border border-black/5 rounded-xl p-3.5 bg-white/80 shadow-sm flex items-center justify-between">
                  <div>
                    <div className="text-xs font-bold text-zinc-800">Quality Target</div>
                    <div className="text-[10px] text-black/45">Min score required to pass</div>
                  </div>
                  <input
                    type="number"
                    value={rules.dq_threshold}
                    onChange={(e) => handleThresholdChange(Number(e.target.value))}
                    className="w-16 text-center border border-black/10 rounded-lg p-1 text-xs font-bold bg-white focus:outline-none focus:ring-2 focus:ring-[#0070AD]/25 text-zinc-900"
                  />
                </div>
              </div>

              {/* Required columns list */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-zinc-800">Mandatory / Required Columns</div>
                <div className="flex flex-wrap gap-2">
                  {(rules.required_columns || []).map((col) => (
                    <span
                      key={col}
                      className="inline-flex items-center gap-1.5 rounded-full bg-[#0070AD]/10 px-3 py-1 text-xs font-bold text-[#0070AD] border border-[#0070AD]/20"
                    >
                      {col}
                      <button
                        onClick={() => removeRequiredCol(col)}
                        className="hover:text-red-600 transition-colors text-[10px]"
                      >
                        <FaTimes />
                      </button>
                    </span>
                  ))}
                  {(rules.required_columns || []).length === 0 && (
                    <span className="text-xs text-black/45 italic">No required columns defined.</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newRequiredCol}
                    onChange={(e) => setNewRequiredCol(e.target.value)}
                    placeholder="Add column..."
                    className="flex-1 border border-black/10 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none text-zinc-900"
                    onKeyDown={(e) => e.key === 'Enter' && addRequiredCol()}
                  />
                  <button
                    onClick={addRequiredCol}
                    className="px-3 py-1.5 bg-zinc-800 text-white rounded-lg text-xs font-bold hover:bg-zinc-900"
                  >
                    Add
                  </button>
                </div>
              </div>

              {/* Non-nullable columns */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-zinc-800">Required Non-Nullable Columns</div>
                <div className="flex flex-wrap gap-2">
                  {(rules.non_nullable || []).map((col) => (
                    <span
                      key={col}
                      className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-800 border border-violet-200"
                    >
                      {col}
                      <button
                        onClick={() => removeNonNullCol(col)}
                        className="hover:text-red-600 transition-colors text-[10px]"
                      >
                        <FaTimes />
                      </button>
                    </span>
                  ))}
                  {(rules.non_nullable || []).length === 0 && (
                    <span className="text-xs text-black/45 italic">No non-nullable constraints.</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newNonNullCol}
                    onChange={(e) => setNewNonNullCol(e.target.value)}
                    placeholder="Add column..."
                    className="flex-1 border border-black/10 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none text-zinc-900"
                    onKeyDown={(e) => e.key === 'Enter' && addNonNullCol()}
                  />
                  <button
                    onClick={addNonNullCol}
                    className="px-3 py-1.5 bg-zinc-800 text-white rounded-lg text-xs font-bold hover:bg-zinc-900"
                  >
                    Add
                  </button>
                </div>
              </div>

              {/* Exclude columns */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-zinc-800">Ignore / Exclude Columns</div>
                <div className="flex flex-wrap gap-2">
                  {(rules.exclude_columns || []).map((col) => (
                    <span
                      key={col}
                      className="inline-flex items-center gap-1.5 rounded-full bg-rose-100 px-3 py-1 text-xs font-bold text-rose-800 border border-rose-200"
                    >
                      {col}
                      <button
                        onClick={() => removeExcludeCol(col)}
                        className="hover:text-red-600 transition-colors text-[10px]"
                      >
                        <FaTimes />
                      </button>
                    </span>
                  ))}
                  {(rules.exclude_columns || []).length === 0 && (
                    <span className="text-xs text-black/45 italic">No excluded columns.</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newExcludeCol}
                    onChange={(e) => setNewExcludeCol(e.target.value)}
                    placeholder="Add column..."
                    className="flex-1 border border-black/10 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none text-zinc-900"
                    onKeyDown={(e) => e.key === 'Enter' && addExcludeCol()}
                  />
                  <button
                    onClick={addExcludeCol}
                    className="px-3 py-1.5 bg-zinc-800 text-white rounded-lg text-xs font-bold hover:bg-zinc-900"
                  >
                    Add
                  </button>
                </div>
              </div>

              {/* Custom Assertions */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-zinc-800">Custom Validation Assertions</div>
                <div className="space-y-2.5">
                  {(rules.custom_assertions || []).map((item, idx) => (
                    <div
                      key={idx}
                      className="border border-black/5 bg-white/90 p-3 rounded-xl shadow-sm flex items-start justify-between gap-4"
                    >
                      <div className="space-y-1 overflow-hidden">
                        <div className="flex items-center gap-2 flex-wrap">
                          <code className="text-xs font-mono font-bold text-zinc-900 truncate max-w-full block bg-black/5 px-2 py-0.5 rounded">
                            {item.assertion}
                          </code>
                          <span
                            className={`px-2 py-0.5 text-[10px] font-black rounded uppercase ${
                              item.severity === 'high'
                                ? 'bg-red-100 text-red-800'
                                : item.severity === 'medium'
                                ? 'bg-amber-100 text-amber-800'
                                : 'bg-blue-100 text-blue-800'
                            }`}
                          >
                            {item.severity}
                          </span>
                        </div>
                        <p className="text-[11px] font-semibold text-black/55">
                          {item.message}
                        </p>
                      </div>
                      <button
                        onClick={() => removeAssertion(idx)}
                        className="text-black/35 hover:text-red-500 p-1.5 transition-colors shrink-0"
                      >
                        <FaTrash className="text-xs" />
                      </button>
                    </div>
                  ))}
                  {(rules.custom_assertions || []).length === 0 && (
                    <div className="text-xs text-black/45 italic">No custom assertions configured.</div>
                  )}
                </div>

                <div className="border border-black/10 rounded-xl p-4 bg-white/60 space-y-3 mt-4">
                  <div className="text-xs font-bold text-zinc-800">Add New Assertion Constraint</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <input
                      type="text"
                      value={newAssertion}
                      onChange={(e) => setNewAssertion(e.target.value)}
                      placeholder="Formula: E.g., Price > 0"
                      className="border border-black/10 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none text-zinc-900"
                    />
                    <input
                      type="text"
                      value={newAssertionMsg}
                      onChange={(e) => setNewAssertionMsg(e.target.value)}
                      placeholder="Message if failed"
                      className="border border-black/10 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none text-zinc-900"
                    />
                  </div>
                  <div className="flex gap-3 items-center justify-between">
                    <div className="flex gap-2 items-center">
                      <span className="text-[10px] font-bold text-black/45 uppercase">Severity:</span>
                      {['low', 'medium', 'high'].map((sev) => (
                        <button
                          key={sev}
                          onClick={() => setNewAssertionSeverity(sev)}
                          className={`px-2 py-0.5 text-[10px] font-bold rounded capitalize ${
                            newAssertionSeverity === sev
                              ? 'bg-zinc-800 text-white'
                              : 'bg-black/5 text-black/50 hover:bg-black/10'
                          }`}
                        >
                          {sev}
                        </button>
                      ))}
                    </div>
                    <button
                      onClick={addAssertion}
                      className="px-4 py-1.5 bg-zinc-800 hover:bg-zinc-900 text-white rounded-lg text-xs font-bold"
                    >
                      Add Assertion
                    </button>
                  </div>
                </div>
              </div>

              {/* General Notes */}
              <div className="flex flex-col space-y-2">
                <label className="text-xs font-bold text-zinc-800">General Notes</label>
                <textarea
                  value={rules.notes || ''}
                  onChange={(e) => setRules({ ...rules, notes: e.target.value })}
                  placeholder="Notes about business logic..."
                  className="w-full h-20 border border-black/10 rounded-lg p-2.5 text-xs bg-white focus:outline-none resize-none font-medium text-zinc-900"
                />
              </div>

              <div className="pt-4 border-t border-black/10">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  disabled={saving}
                  onClick={handleSaveAndProceed}
                  className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-[#0070AD] text-white font-bold hover:bg-[#005f94] transition-colors disabled:opacity-50 text-sm"
                >
                  {saving ? (
                    <>
                      <FaSpinner className="animate-spin text-lg" />
                      Saving Rules context…
                    </>
                  ) : (
                    <>
                      Continue to Data Assessment
                      <FaArrowRight className="text-sm" />
                    </>
                  )}
                </motion.button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
