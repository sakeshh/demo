'use client';

import { motion, useReducedMotion } from 'framer-motion';

const FLOW_LINES = [
  { top: '8%', delay: '0s', speed: 'animate-flow-line', color: 'brand' as const, depth: 0.5 },
  { top: '18%', delay: '-4s', speed: 'animate-flow-line-reverse-slow', color: 'light' as const, depth: 0.65 },
  { top: '28%', delay: '-8s', speed: 'animate-flow-line-fast', color: 'blend' as const, depth: 0.8 },
  { top: '38%', delay: '-2s', speed: 'animate-flow-line-reverse', color: 'light' as const, depth: 1 },
  { top: '52%', delay: '-12s', speed: 'animate-flow-line-slow', color: 'blend' as const, depth: 1 },
  { top: '62%', delay: '-6s', speed: 'animate-flow-line-reverse', color: 'brand' as const, depth: 0.8 },
  { top: '72%', delay: '-10s', speed: 'animate-flow-line-fast', color: 'light' as const, depth: 0.65 },
  { top: '85%', delay: '-3s', speed: 'animate-flow-line-slow', color: 'brand' as const, depth: 0.5 },
];

export default function AnimatedBackground({ className = '' }: { className?: string }) {
  const reduceMotion = useReducedMotion();

  return (
    <div className={`absolute inset-0 overflow-hidden ${className}`}>
      {/* Split-screen base wash: white ↔ brand blues */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(90deg, rgba(255,255,255,1) 0%, rgba(255,255,255,1) 48%, rgba(255,255,255,0.92) 52%, rgba(0,112,173,0.10) 62%, rgba(18,171,219,0.16) 100%)',
        }}
      />
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(90% 90% at 52% 55%, rgba(0,112,173,0.14) 0%, rgba(0,112,173,0.06) 38%, transparent 72%)',
          mixBlendMode: 'multiply',
        }}
      />

      {/* Soft drifting spotlights */}
      <motion.div
        aria-hidden
        className="absolute left-[15%] top-[20%] h-[700px] w-[700px] rounded-full blur-[120px]"
        style={{
          background: 'radial-gradient(circle, rgba(0,112,173,0.12) 0%, rgba(0,112,173,0.04) 35%, transparent 70%)',
        }}
        initial={{ opacity: 0 }}
        animate={reduceMotion ? { opacity: 0.8, x: 0, y: 0 } : { opacity: [0, 0.7, 1, 0.8, 0.7], x: [0, 80, -40, 0], y: [0, -60, 40, 0] }}
        transition={reduceMotion ? { duration: 0 } : { opacity: { times: [0, 0.02, 0.04, 0.5, 1], duration: 28, repeat: Infinity, ease: 'easeInOut' }, x: { duration: 28, repeat: Infinity, ease: 'easeInOut' }, y: { duration: 28, repeat: Infinity, ease: 'easeInOut' } }}
      />
      <motion.div
        aria-hidden
        className="absolute bottom-[10%] right-[10%] h-[600px] w-[600px] rounded-full blur-[100px]"
        style={{
          background: 'radial-gradient(circle, rgba(18,171,219,0.1) 0%, rgba(18,171,219,0.03) 40%, transparent 70%)',
        }}
        initial={{ opacity: 0 }}
        animate={reduceMotion ? { opacity: 0.7, x: 0, y: 0 } : { opacity: [0, 0.6, 0.95, 0.7, 0.6], x: [0, -100, 50, 0], y: [0, 50, -30, 0] }}
        transition={reduceMotion ? { duration: 0 } : { opacity: { times: [0, 0.02, 0.04, 0.5, 1], duration: 32, repeat: Infinity, ease: 'easeInOut', delay: 0.2 }, x: { duration: 32, repeat: Infinity, ease: 'easeInOut', delay: 0.2 }, y: { duration: 32, repeat: Infinity, ease: 'easeInOut', delay: 0.2 } }}
      />
      <motion.div
        aria-hidden
        className="absolute left-1/2 top-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[110px]"
        style={{
          background: 'radial-gradient(circle, rgba(139,92,246,0.06) 0%, rgba(0,112,173,0.05) 50%, transparent 70%)',
        }}
        initial={{ opacity: 0 }}
        animate={reduceMotion ? { scale: 1, opacity: 0.6 } : { scale: [1, 1.15, 1.05, 1], opacity: [0, 0.5, 0.8, 0.6, 0.5] }}
        transition={reduceMotion ? { duration: 0 } : { scale: { duration: 24, repeat: Infinity, ease: 'easeInOut', delay: 0.4 }, opacity: { times: [0, 0.02, 0.04, 0.5, 1], duration: 24, repeat: Infinity, ease: 'easeInOut', delay: 0.4 } }}
      />

      {/* Grid */}
      <motion.div
        className="absolute inset-0 opacity-[0.18]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.18 }}
        transition={{ duration: 0.8, delay: 0.6 }}
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.06) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
          backgroundPosition: 'center',
          maskImage: 'radial-gradient(ellipse at center, black 45%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 45%, transparent 75%)',
        }}
      />

      {/* Data stream / flow lines — parallax drift */}
      <motion.div
        aria-hidden
        className="absolute inset-0 overflow-hidden"
        style={{
          maskImage: 'radial-gradient(ellipse 80% 70% at 50% 50%, black 30%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at 50% 50%, black 30%, transparent 75%)',
        }}
        initial={{ opacity: 0 }}
        animate={reduceMotion ? { opacity: 0.35, x: 0, y: 0 } : { opacity: 0.35, x: [0, 28, -18, 0], y: [0, -22, 24, 0] }}
        transition={reduceMotion ? { opacity: { duration: 0.7, delay: 0.8 }, x: { duration: 0 }, y: { duration: 0 } } : { opacity: { duration: 0.7, delay: 0.8 }, x: { duration: 42, repeat: Infinity, ease: 'easeInOut' }, y: { duration: 42, repeat: Infinity, ease: 'easeInOut' } }}
      >
        {FLOW_LINES.map((line, i) => {
          const d = line.depth;
          const blendBase = 'linear-gradient(90deg, transparent 0%, rgba(0,112,173,0.15) 20%, rgba(18,171,219,0.35) 50%, rgba(0,112,173,0.15) 80%, transparent 100%)';
          const blendPacket = 'linear-gradient(90deg, transparent 0%, transparent 22%, rgba(0,112,173,0.6) 35%, rgba(18,171,219,0.95) 50%, rgba(0,112,173,0.6) 65%, transparent 78%, transparent 100%)';
          const brandBg = `linear-gradient(90deg, transparent 0%, rgba(0,112,173,${0.2 * d}) 30%, rgba(0,112,173,${0.35 * d}) 50%, rgba(0,112,173,${0.2 * d}) 70%, transparent 100%), linear-gradient(90deg, transparent 0%, transparent 22%, rgba(0,112,173,${0.5 * d}) 38%, rgba(0,112,173,${0.95 * d}) 50%, rgba(0,112,173,${0.5 * d}) 62%, transparent 78%, transparent 100%)`;
          const lightBg = `linear-gradient(90deg, transparent 0%, rgba(18,171,219,${0.18 * d}) 30%, rgba(18,171,219,${0.3 * d}) 50%, rgba(18,171,219,${0.18 * d}) 70%, transparent 100%), linear-gradient(90deg, transparent 0%, transparent 22%, rgba(18,171,219,${0.45 * d}) 38%, rgba(18,171,219,${0.9 * d}) 50%, rgba(18,171,219,${0.45 * d}) 62%, transparent 78%, transparent 100%)`;
          const blendBg = `${blendBase}, ${blendPacket}`;
          const background = line.color === 'brand' ? brandBg : line.color === 'light' ? lightBg : blendBg;
          const glowColor = line.color === 'brand' ? 'rgba(0,112,173,0.25)' : line.color === 'light' ? 'rgba(18,171,219,0.2)' : 'rgba(18,171,219,0.22)';
          return (
            <div
              key={i}
              className={`absolute left-0 h-px w-[min(80vw,400px)] ${line.speed}`}
              style={{
                top: line.top,
                animationDelay: line.delay,
                background,
                backgroundSize: '100% 100%, 72px 100%',
                backgroundRepeat: 'no-repeat, repeat-x',
                boxShadow: `0 0 12px 1px ${glowColor}`,
              }}
            />
          );
        })}
      </motion.div>

      {/* Ambient orbs */}
      <motion.div
        aria-hidden
        className="absolute -bottom-56 right-[-120px] h-[520px] w-[520px] rounded-full bg-gradient-to-br from-[#0070AD]/12 via-transparent to-[#12ABDB]/12 blur-[80px]"
        initial={{ opacity: 0 }}
        animate={reduceMotion ? { x: 0, opacity: 0.65 } : { x: [0, -6, 0], opacity: [0, 0.5, 0.8, 0.5] }}
        transition={reduceMotion ? { duration: 0 } : { opacity: { times: [0, 0.02, 0.5, 1], duration: 22, repeat: Infinity, ease: 'easeInOut', delay: 1.1 }, x: { duration: 22, repeat: Infinity, ease: 'easeInOut', delay: 1.1 } }}
      />

      {/* Vignette + noise */}
      <div className="vignette-overlay absolute inset-0" aria-hidden />
      <div className="noise-overlay absolute inset-0" aria-hidden />
    </div>
  );
}
