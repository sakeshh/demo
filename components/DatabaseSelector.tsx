'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FaDatabase, FaSearch, FaFolder, FaCloud, FaStream, FaPlug, FaArrowLeft } from 'react-icons/fa';

interface DatabaseSelectorProps {
  onSelect: (database: string) => void;
  onBack?: () => void;
}

type SourceLocation = { index: number; id?: string | null; type?: string | null };

const SOURCE_TYPE_TO_CARD: Record<string, { id: string; text: string; icon: any }> = {
  database: { id: 'sql', text: 'SQL data', icon: FaDatabase },
  azure_blob: { id: 'blob', text: 'Blob data', icon: FaCloud },
  filesystem: { id: 'streams', text: 'File stream', icon: FaStream },
  local: { id: 'local', text: 'Local data', icon: FaFolder },
};

function normalizeType(t: any): string {
  const s = String(t || '').toLowerCase();
  if (s.includes('azure_blob')) return 'azure_blob';
  if (s.includes('filesystem')) return 'filesystem';
  if (s.includes('database')) return 'database';
  return s || 'unknown';
}

export default function DatabaseSelector({ onSelect, onBack }: DatabaseSelectorProps) {
  const [selectedDataSource, setSelectedDataSource] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<SourceLocation[]>([]);

  const refreshLocations = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/sources');
      const data = await res.json().catch(() => null);
      const locs = Array.isArray(data?.locations) ? data.locations : [];
      setLocations(
        locs.map((x: any) => ({
          index: Number(x?.index ?? 0),
          id: x?.id ?? null,
          type: x?.type ?? null,
        }))
      );
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const filteredLocations = locations
    .filter((l) => normalizeType(l.type) !== 'azure_blob_output') // pipeline inputs only
    .filter((l) => {
      if (!selectedDataSource) return false;
      const nt = normalizeType(l.type);
      if (selectedDataSource === 'sql') return nt === 'database';
      if (selectedDataSource === 'blob') return nt === 'azure_blob';
      if (selectedDataSource === 'streams') return nt === 'filesystem';
      return false;
    })
    .filter((l) => {
      const q = searchTerm.trim().toLowerCase();
      if (!q) return true;
      const label = String(l.id || '').toLowerCase();
      const tp = normalizeType(l.type);
      return label.includes(q) || tp.includes(q) || String(l.index).includes(q);
    });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch('/api/sources');
        const data = await res.json().catch(() => null);
        const locs = Array.isArray(data?.locations) ? data.locations : [];
        if (!alive) return;
        setLocations(
          locs.map((x: any) => ({
            index: Number(x?.index ?? 0),
            id: x?.id ?? null,
            type: x?.type ?? null,
          }))
        );
      } catch {
        // ignore
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (selectedDataSource) {
      setSearchTerm('');
    }
  }, [selectedDataSource]);

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        {onBack && (
          <motion.button
            onClick={onBack}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-black/60 hover:text-black transition-colors shrink-0 order-first"
            whileHover={{ x: -2 }}
            whileTap={{ scale: 0.98 }}
          >
            <FaArrowLeft className="w-4 h-4" />
            Back
          </motion.button>
        )}
        <div className="flex-1">
          <h2 className="text-3xl font-bold text-zinc-900 mb-2">Select Data Source</h2>
          <p className="text-black/60">Choose where your data comes from, then select the specific source</p>
        </div>
        <div className="shrink-0">
          <motion.button
            type="button"
            onClick={refreshLocations}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-black/10 bg-white/80 text-sm font-medium text-black/70 hover:bg-white hover:border-[#0070AD]/30 transition-colors"
          >
            <FaPlug className="text-[#0070AD]/80" />
            Refresh sources
          </motion.button>
        </div>
      </div>

      {/* Choose one - Data source type options (matching chat choose box) */}
      <div>
        <p className="text-sm font-medium text-black/70 mb-3">Choose one:</p>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-3 gap-3">
          {(['sql', 'blob', 'streams'] as const).map((id, idx) => {
            const option =
              id === 'sql'
                ? SOURCE_TYPE_TO_CARD.database
                : id === 'blob'
                  ? SOURCE_TYPE_TO_CARD.azure_blob
                  : SOURCE_TYPE_TO_CARD.filesystem;
            const Icon = option.icon;
            const isSelected = selectedDataSource === id;
            return (
              <motion.button
                key={id}
                onClick={() => setSelectedDataSource(id)}
                className={`flex items-center gap-3 p-4 text-sm font-medium text-left rounded-xl border transition-all ${
                  isSelected
                    ? 'bg-[#0070AD]/15 border-[#0070AD]/50 text-zinc-900'
                    : 'bg-white/85 border-black/10 text-black/70 hover:border-[#0070AD]/30 hover:bg-white'
                }`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05 }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <Icon className="text-xl text-[#0070AD]/80 flex-shrink-0" />
                <span>{option.text}</span>
              </motion.button>
            );
          })}
        </div>
      </div>

      {/* Back button when a data source is selected (step 2) */}
      {selectedDataSource && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex items-center gap-4"
        >
          <motion.button
            onClick={() => setSelectedDataSource(null)}
            className="flex items-center gap-2 text-sm font-medium text-black/60 hover:text-black transition-colors"
            whileHover={{ x: -2 }}
            whileTap={{ scale: 0.98 }}
          >
            <FaArrowLeft className="w-4 h-4" />
            Back to data source type
          </motion.button>
          {onBack && (
            <motion.button
              onClick={onBack}
              className="flex items-center gap-2 text-sm text-black/60 hover:text-black transition-colors"
            >
              ← Back
            </motion.button>
          )}
        </motion.div>
      )}

      {/* Options grid based on selected data source */}
      <AnimatePresence mode="wait">
        {selectedDataSource ? (
          <motion.div
            key={selectedDataSource}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-4"
          >
            <p className="text-sm font-medium text-black/70">
              Select {selectedDataSource === 'sql' ? 'database' : selectedDataSource === 'blob' ? 'blob source' : 'filesystem source'}:
            </p>
            <div className="relative">
              <FaSearch className="absolute left-4 top-1/2 -translate-y-1/2 text-black/45" />
              <input
                type="text"
                placeholder={`Search ${selectedDataSource} sources...`}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-12 pr-4 py-3 border border-black/10 rounded-xl focus:ring-2 focus:ring-[#0070AD]/25 focus:border-[#0070AD]/40 outline-none bg-white/90 text-zinc-900 placeholder-black/40"
              />
            </div>
            {loading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <div key={i} className="h-32 bg-white/10 animate-pulse rounded-xl" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredLocations.map((item, index) => (
                  <motion.button
                    key={`${item.index}-${item.id ?? item.type ?? 'src'}`}
                    onClick={() => onSelect(`src:${selectedDataSource}:${item.index}`)}
                    className="p-6 bg-white/85 border border-black/10 rounded-xl hover:border-[#0070AD]/30 hover:bg-white transition-all text-left group"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05 }}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                  >
                    <div className="flex items-start gap-4">
                      <div className="p-3 bg-black/5 rounded-lg group-hover:bg-[#0070AD]/10 transition-colors">
                        <FaDatabase className="text-2xl text-[#0070AD]/80" />
                      </div>
                      <div className="flex-1">
                        <h3 className="font-semibold text-zinc-900 mb-1">
                          {item.id ? String(item.id) : `Source #${item.index}`}
                        </h3>
                        <p className="text-sm text-black/60 capitalize">
                          {normalizeType(item.type)}
                        </p>
                      </div>
                    </div>
                  </motion.button>
                ))}
              </div>
            )}
            {filteredLocations.length === 0 && !loading && (
              <div className="text-center py-12">
                <FaDatabase className="text-6xl text-black/30 mx-auto mb-4" />
                <p className="text-black/60">No options found matching your search</p>
              </div>
            )}
          </motion.div>
        ) : (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-sm text-black/60"
          >
            Select a data source type above to see available options.
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
