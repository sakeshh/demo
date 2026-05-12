'use client';

import { motion } from 'framer-motion';
import { FaCheckCircle, FaExclamationTriangle, FaTachometerAlt, FaClock } from 'react-icons/fa';

export default function Monitoring({ gxEnabled = false }: { gxEnabled?: boolean }) {
  const performanceMetrics = [
    { label: 'Throughput', value: '1.2K/s', icon: FaTachometerAlt, color: gxEnabled ? 'text-emerald-400' : 'text-[#12ABDB]/80' },
    { label: 'Latency', value: '45ms', icon: FaClock, color: gxEnabled ? 'text-white/60' : 'text-white/50' },
    { label: 'Success Rate', value: '99.8%', icon: FaCheckCircle, color: gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]' },
  ];

  const alerts = [
    { id: 1, type: 'warning', message: 'High memory usage detected', time: '2m ago' },
    { id: 2, type: 'info', message: 'Pipeline completed successfully', time: '15m ago' },
  ];

  const logs = [
    { id: 1, timestamp: '14:23:45', status: 'success', message: 'Data validation passed' },
    { id: 2, timestamp: '14:22:30', status: 'success', message: 'Transformation applied' },
    { id: 3, timestamp: '14:21:15', status: 'info', message: 'Pipeline started' },
  ];

  return (
    <motion.div
      className="space-y-4"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.3, ease: 'easeOut' }}
    >
      <h3 className={`mb-3 text-xs font-semibold uppercase tracking-wide ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>
        Monitoring & Optimization
      </h3>

      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.2 }}
        className={`rounded-xl border p-3 transition-all ${
          gxEnabled ? 'border-emerald-500/30 bg-emerald-500/10' : 'border-[#0070AD]/30 bg-[#0070AD]/10'
        }`}
      >
        <div className="mb-1 flex items-center gap-2">
          <FaCheckCircle className={gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]'} />
          <span className={`text-xs font-semibold ${gxEnabled ? 'text-emerald-400' : 'text-[#0070AD]'}`}>Pipeline Health</span>
        </div>
        <p className={`text-lg font-bold ${gxEnabled ? 'text-white' : 'text-[#0070AD]'}`}>Healthy</p>
      </motion.div>

      <div>
        <label className={`mb-2 block text-xs font-medium ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>Performance Metrics</label>
        <div className="space-y-2">
          {performanceMetrics.map((metric, i) => {
            const Icon = metric.icon;
            return (
              <motion.div
                key={metric.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 * i }}
                className={`flex items-center justify-between rounded-xl border p-2 transition-all ${
                  gxEnabled ? 'border-white/10 bg-[#002B45]/80' : 'border-black/10 bg-white/85'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon className={`${metric.color} text-sm`} />
                  <span className={`text-xs font-medium ${gxEnabled ? 'text-white/60' : 'text-black/70'}`}>{metric.label}</span>
                </div>
                <span className={`text-xs font-bold ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>{metric.value}</span>
              </motion.div>
            );
          })}
        </div>
      </div>

      <div>
        <label className={`mb-2 block text-xs font-medium ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>Recent Alerts</label>
        <div className="max-h-32 space-y-2 overflow-y-auto">
          {alerts.map((alert, i) => (
            <motion.div
              key={alert.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.05 * i }}
              className={`rounded-xl border p-2 text-xs transition-all ${
                alert.type === 'warning'
                  ? gxEnabled ? 'border-amber-500/40 bg-amber-500/10' : 'border-amber-400/40 bg-amber-500/10'
                  : gxEnabled ? 'border-white/10 bg-[#002B45]/80' : 'border-black/10 bg-white/85'
              }`}
            >
              <div className="flex items-start gap-2">
                {alert.type === 'warning' ? (
                  <FaExclamationTriangle className="mt-0.5 flex-shrink-0 text-amber-400" />
                ) : (
                  <FaCheckCircle className={`mt-0.5 flex-shrink-0 ${gxEnabled ? 'text-emerald-400' : 'text-black/45'}`} />
                )}
                <div className="min-w-0 flex-1">
                  <p className={`truncate font-medium ${gxEnabled ? 'text-white' : 'text-zinc-900'}`}>{alert.message}</p>
                  <p className={`text-[10px] ${gxEnabled ? 'text-white/30' : 'text-black/45'}`}>{alert.time}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      <div>
        <label className={`mb-2 block text-xs font-medium ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>Historical Logs</label>
        <div className={`overflow-hidden rounded-xl border transition-all ${gxEnabled ? 'border-white/10 bg-[#002B45]/80' : 'border-black/10 bg-white/85'}`}>
          <div className="max-h-40 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className={`sticky top-0 transition-all ${gxEnabled ? 'bg-[#001D2E]' : 'bg-white'}`}>
                <tr>
                  <th className={`px-2 py-1.5 text-left font-semibold ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>Time</th>
                  <th className={`px-2 py-1.5 text-left font-semibold ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>Status</th>
                  <th className={`px-2 py-1.5 text-left font-semibold ${gxEnabled ? 'text-emerald-400' : 'text-black/55'}`}>Message</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr
                    key={log.id}
                    className={`border-t transition-colors ${gxEnabled ? 'border-white/10 hover:bg-white/5' : 'border-black/10 hover:bg-black/5'}`}
                  >
                    <td className={`whitespace-nowrap px-2 py-1.5 ${gxEnabled ? 'text-white/40' : 'text-black/55'}`}>{log.timestamp}</td>
                    <td className="px-2 py-1.5">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          log.status === 'success'
                            ? gxEnabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[#0070AD]/10 text-[#0070AD]'
                            : gxEnabled ? 'bg-white/5 text-white/40' : 'bg-black/5 text-black/55'
                        }`}
                      >
                        {log.status}
                      </span>
                    </td>
                    <td className={`px-2 py-1.5 ${gxEnabled ? 'text-white/70' : 'text-black/80'}`}>{log.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
