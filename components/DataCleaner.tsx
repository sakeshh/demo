'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FaBroom, FaDownload, FaCheckCircle, FaThumbsUp, FaThumbsDown, FaExclamationTriangle } from 'react-icons/fa';

interface DataCleanerProps {
  files: string[];
  etlCode: string | null;
  assessmentData: any;
  userFeedback: Array<{ step: string; liked: boolean; comment?: string }>;
  onComplete: () => void;
  onFeedback: (liked: boolean, comment?: string) => void;
}

interface CleaningResult {
  fileName: string;
  originalRows: number;
  cleanedRows: number;
  duplicatesRemoved: number;
  missingValuesHandled: number;
  blobUrl: string;
}

export default function DataCleaner({ files, etlCode, assessmentData, userFeedback, onComplete, onFeedback }: DataCleanerProps) {
  const [showConfirmation, setShowConfirmation] = useState(true);
  const [cleaning, setCleaning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentFile, setCurrentFile] = useState('');
  const [results, setResults] = useState<CleaningResult[]>([]);
  const [learningFromFeedback, setLearningFromFeedback] = useState(false);

  const handleConfirm = () => {
    setShowConfirmation(false);
    startCleaning();
  };

  const startCleaning = async () => {
    setCleaning(true);
    
    if (userFeedback.some(f => !f.liked)) {
      setLearningFromFeedback(true);
      await new Promise(resolve => setTimeout(resolve, 2000));
      setLearningFromFeedback(false);
    }

    const cleaningResults: CleaningResult[] = [];

    for (let i = 0; i < files.length; i++) {
      setCurrentFile(files[i]);
      
      for (let p = 0; p <= 100; p += 5) {
        await new Promise(resolve => setTimeout(resolve, 50));
        setProgress(((i * 100 + p) / files.length));
      }

      const originalRows = Math.floor(Math.random() * 100000) + 10000;
      const duplicatesRemoved = Math.floor(Math.random() * 1000) + 100;
      const missingValuesHandled = Math.floor(Math.random() * 500) + 50;
      
      cleaningResults.push({
        fileName: files[i],
        originalRows,
        cleanedRows: originalRows - duplicatesRemoved,
        duplicatesRemoved,
        missingValuesHandled,
        blobUrl: `https://storage.blob.core.windows.net/cleaned-data/${files[i]}_cleaned_${Date.now()}.csv`
      });
    }

    setResults(cleaningResults);
    setCleaning(false);
  };

  const handleDownloadAll = () => {
    results.forEach(result => {
      console.log(`Downloading: ${result.blobUrl}`);
    });
    alert('All cleaned files downloaded! (In production, files would be downloaded from blob storage)');
  };

  const handleLike = () => {
    onFeedback(true);
    setTimeout(() => {
      onComplete();
    }, 1000);
  };

  const handleDislike = () => {
    const comment = prompt('What would you like us to improve in the data cleaning?');
    onFeedback(false, comment || undefined);
    
    setTimeout(() => {
      alert('Thank you for your feedback! We are learning from your input and will improve the cleaning process...');
      setResults([]);
      setCleaning(false);
      setShowConfirmation(true);
    }, 500);
  };

  if (showConfirmation) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="flex flex-col items-center justify-center space-y-8 py-10"
      >
        <div className="relative">
          <div className="absolute inset-0 scale-150 blur-3xl bg-gradient-to-tr from-amber-500/20 to-orange-500/20 animate-pulse" />
          <div className="relative flex h-24 w-24 items-center justify-center rounded-3xl bg-white shadow-2xl">
            <FaExclamationTriangle className="text-4xl text-amber-500" />
          </div>
        </div>

        <div className="text-center space-y-3">
          <h2 className="text-4xl font-black tracking-tight text-zinc-900">Execution Guard</h2>
          <p className="text-lg font-medium text-black/40">Confirming bulk data remediation on {files.length} sources</p>
        </div>

        <div className="w-full max-w-xl rounded-3xl border border-black/10 bg-white/60 p-8 shadow-xl backdrop-blur-md">
          <h3 className="text-sm font-black uppercase tracking-widest text-black/30 mb-6">Remediation Blueprint</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[
              { label: 'Deduplication', desc: 'Identify and prune redundant rows' },
              { label: 'Missing Value Fix', desc: 'Impute via median/mode synthesis' },
              { label: 'Type Casting', desc: 'Normalize schema for downstream ETL' },
              { label: 'Cloud Sync', desc: 'Persist artifacts to Blob Storage' },
            ].map((item, i) => (
              <div key={i} className="flex items-start gap-4 rounded-2xl border border-black/5 bg-white/40 p-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#0070AD]/10 text-[#0070AD]">
                  <FaCheckCircle className="text-sm" />
                </div>
                <div>
                  <div className="text-[13px] font-black text-zinc-900">{item.label}</div>
                  <div className="text-[11px] font-medium text-black/40">{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex w-full max-w-xl gap-4">
          <motion.button
            onClick={handleConfirm}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex-1 py-5 bg-gradient-to-r from-[#0070AD] to-[#12ABDB] text-white text-sm font-black uppercase tracking-widest rounded-2xl shadow-xl shadow-[#0070AD]/20 hover:shadow-2xl transition-all"
          >
            Execute Cleaning
          </motion.button>
          <motion.button
            onClick={onComplete}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex-1 py-5 bg-white border border-black/10 text-zinc-800 text-sm font-black uppercase tracking-widest rounded-2xl hover:bg-zinc-50 transition-all"
          >
            Bypass
          </motion.button>
        </div>
      </motion.div>
    );
  }

  if (cleaning) {
    return (
      <div className="flex flex-col items-center justify-center space-y-10 py-16">
        <div className="relative">
          <div className="absolute inset-0 scale-150 blur-3xl bg-gradient-to-tr from-[#0070AD]/20 to-[#12ABDB]/20 animate-pulse" />
          <motion.div 
            animate={{ rotate: 360 }}
            transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
            className="relative flex h-24 w-24 items-center justify-center rounded-3xl bg-white shadow-2xl"
          >
            <FaBroom className="text-4xl text-[#0070AD]" />
          </motion.div>
        </div>
        
        <div className="text-center space-y-3">
          <h2 className="text-4xl font-black tracking-tight text-zinc-900">
            {learningFromFeedback ? 'Intelligence Adaptation' : 'Data Remediation'}
          </h2>
          <p className="text-lg font-medium text-black/40">
            {learningFromFeedback ? 'Refining strategy from your feedback...' : `Scrubbing ${currentFile}...`}
          </p>
        </div>

        <div className="w-full max-w-md space-y-4">
          <div className="relative h-3 w-full bg-black/5 rounded-full overflow-hidden border border-black/5">
            <motion.div
              className="h-full bg-gradient-to-r from-[#0070AD] via-[#12ABDB] to-[#0070AD] bg-[length:200%_auto]"
              animate={{ width: `${progress}%`, backgroundPosition: ['0% 0%', '100% 0%'] }}
              transition={{ backgroundPosition: { duration: 2, repeat: Infinity, ease: 'linear' } }}
            />
          </div>
          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] font-black uppercase tracking-widest text-black/30">Scrubbing Progress</span>
            <span className="text-xl font-black text-[#0070AD]">{Math.floor(progress)}%</span>
          </div>
        </div>

        {learningFromFeedback && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-4 rounded-2xl border border-amber-200 bg-amber-50/50 p-6 backdrop-blur-sm"
          >
            <div className="text-2xl">🧠</div>
            <div>
              <div className="text-sm font-black text-amber-900">AI Context Injection</div>
              <div className="text-[12px] font-medium text-amber-800/60">Optimizing heuristic weights based on user preferences.</div>
            </div>
          </motion.div>
        )}
      </div>
    );
  }

  if (results.length > 0) {
    return (
      <div className="space-y-8">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-4xl font-black tracking-tight text-zinc-900">Cleaning Complete</h2>
            <p className="text-lg font-medium text-black/40">Refined datasets have been committed to storage</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleLike}
              className="group flex h-14 w-14 items-center justify-center rounded-2xl border border-[#0070AD]/20 bg-white shadow-sm transition-all hover:bg-[#0070AD] hover:text-white"
            >
              <FaThumbsUp className="text-xl transition-transform group-hover:scale-125" />
            </button>
            <button
              onClick={handleDislike}
              className="group flex h-14 w-14 items-center justify-center rounded-2xl border-red-500/20 bg-white shadow-sm transition-all hover:bg-red-500 hover:text-white"
            >
              <FaThumbsDown className="text-xl transition-transform group-hover:scale-125" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6">
          {results.map((result, idx) => (
            <motion.div
              key={result.fileName}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="group relative overflow-hidden rounded-3xl border border-[#0070AD]/30 bg-white/60 p-8 shadow-xl backdrop-blur-md"
            >
              <div className="mb-8 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0070AD] to-[#12ABDB] text-white shadow-lg">
                    <FaCheckCircle className="text-xl" />
                  </div>
                  <div>
                    <h3 className="text-xl font-black text-zinc-900">{result.fileName}</h3>
                    <p className="text-[12px] font-bold text-black/30 uppercase tracking-widest">Remediation Success</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  { label: 'Original', value: result.originalRows, sub: 'Total Rows', color: 'text-zinc-500' },
                  { label: 'Result', value: result.cleanedRows, sub: 'Cleaned Rows', color: 'text-[#0070AD]' },
                  { label: 'Pruned', value: result.duplicatesRemoved, sub: 'Duplicates', color: 'text-red-500' },
                  { label: 'Resolved', value: result.missingValuesHandled, sub: 'Null Values', color: 'text-amber-500' },
                ].map((stat, i) => (
                  <div key={i} className="rounded-2xl border border-black/5 bg-white/40 p-5 shadow-sm">
                    <div className="text-[10px] font-black uppercase tracking-widest text-black/30 mb-1">{stat.label}</div>
                    <div className={`text-2xl font-black ${stat.color}`}>{stat.value.toLocaleString()}</div>
                    <div className="text-[11px] font-medium text-black/40">{stat.sub}</div>
                  </div>
                ))}
              </div>

              <div className="mt-8 rounded-2xl border border-[#0070AD]/10 bg-[#0070AD]/5 p-5">
                <div className="text-[10px] font-black uppercase tracking-widest text-[#0070AD] mb-3">Cloud Storage Deployment</div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <code className="flex-1 overflow-x-auto rounded-xl border border-[#0070AD]/20 bg-white/80 p-3 font-mono text-[11px] text-[#0070AD]">
                    {result.blobUrl}
                  </code>
                  <motion.button
                    onClick={() => {
                      navigator.clipboard.writeText(result.blobUrl);
                      alert('URL copied to clipboard!');
                    }}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    className="flex h-11 items-center justify-center rounded-xl bg-[#0070AD] px-6 text-[12px] font-black text-white shadow-lg transition-all hover:bg-[#12ABDB]"
                  >
                    COPY LINK
                  </motion.button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        <div className="flex gap-4 pt-4">
          <motion.button
            onClick={handleDownloadAll}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex-1 flex items-center justify-center gap-3 py-5 bg-gradient-to-r from-zinc-900 to-zinc-800 text-white text-sm font-black uppercase tracking-widest rounded-2xl shadow-xl transition-all"
          >
            <FaDownload />
            <span>Download All Artifacts</span>
          </motion.button>
          <motion.button
            onClick={handleLike}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex-1 py-5 bg-gradient-to-r from-[#0070AD] to-[#12ABDB] text-white text-sm font-black uppercase tracking-widest rounded-2xl shadow-xl shadow-[#0070AD]/20 transition-all"
          >
            Finish Pipeline
          </motion.button>
        </div>
      </div>
    );
  }

  return null;
}
