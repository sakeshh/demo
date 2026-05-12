'use client';

import { motion, useReducedMotion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import SogetiLogo from '@/components/SogetiLogo';
import AnimatedBackground from '@/components/AnimatedBackground';
import { FaRocket } from 'react-icons/fa';

const THREAD_TILE = 800;
/** Fewer threads + steps for smooth performance; no per-thread JS animation. */
const THREAD_COUNT = 18;
const THREAD_STEPS = 48;
/** Vertical center of ribbon in viewBox units. */
const BUNDLE_CENTERY = 176;
/** ViewBox height — room for pinch + helix + sway. */
const RIBBON_VB_H = 420;
/** Main centerline wander (seamless 1× tile period). */
/** Helix / “twist around axis” (per thread + along x). */
const SNAKE_RADIUS_MAX = 135;
const SNAKE_TWIST_PER_TILE = 5;
const BODY_SWAY = 20;
const TRAIL_PHASE = 0.5;
const MID = (THREAD_COUNT - 1) / 2;

/**
 * 3D ribbon + motion. Horizontal tile: wx uses integer cycles on THREAD_TILE.
 * Vertical time loop: flowAngle only appears as integer multiples inside each sin/cos so a 2π jump
 * in flowAngle leaves every term unchanged → no “restart” pop. Per-thread integers give independent rhythms.
 */
function ribbonThreadPathD(
  i: number,
  bundlePhase: number,
  muted: boolean,
  /** Elapsed flow angle (radians); unbounded OK — trig wraps; avoid % in parent for smooth derivative. */
  flowAngle: number,
): string {
  const m = muted ? 0.78 : 1;
  const parts: string[] = [];
  const T = 2 * Math.PI;
  const baseAngle = (T * i) / THREAD_COUNT;
  const fa = flowAngle;
  const kDir = (i % 2 === 0 ? 1 : -1) * (1 + (i % 3));

  for (let s = 0; s <= THREAD_STEPS; s++) {
    const x = (THREAD_TILE * s) / THREAD_STEPS;
    const wx = (T * x) / THREAD_TILE;
    const pinch =
      0.38 +
      0.62 *
        (0.5 +
          0.5 *
            Math.cos(
              2 * wx + bundlePhase * 1.2 + 2 * fa + (i / THREAD_COUNT) * T * 0.3,
            ));
    const R = SNAKE_RADIUS_MAX * m * pinch;
    const theta =
      baseAngle +
      (T * SNAKE_TWIST_PER_TILE * x) / THREAD_TILE +
      fa * kDir +
      bundlePhase * 0.5;
    const yCircle = R * Math.sin(theta);
    const bodySway =
      BODY_SWAY * m * Math.sin(wx + bundlePhase * 0.8 + fa) +
      8 * m * Math.sin(2 * wx + 2 * fa + bundlePhase * 0.3);
    const y = BUNDLE_CENTERY + bodySway + yCircle;
    parts.push(`${s === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(3)}`);
  }
  return parts.join(' ');
}

/** Brand-blue strokes; slight variation for depth. */
function strokeForThread(i: number, muted: boolean): { stroke: string; w: number } {
  const un = MID === 0 ? 0 : (i - MID) / MID;
  const edge = Math.abs(un);
  const core = Math.max(0, 1 - edge);
  if (muted) {
    const a = 0.12 + core * 0.08;
    return { stroke: `rgba(0,112,173,${a})`, w: 0.7 + core * 0.25 };
  }
  const a = 0.28 + core * 0.18;
  return { stroke: `rgba(0,112,173,${a})`, w: 0.85 + core * 0.2 };
}

/** Parallel phased threads: reads like a rotating bundle / circular flow; no crossings by construction. */
function ThreadBundleSvg({
  idSuffix,
  className,
  muted = false,
  bundlePhase = 0,
  flowAngle = 0,
}: {
  idSuffix: string;
  className?: string;
  muted?: boolean;
  bundlePhase?: number;
  flowAngle?: number;
}) {
  const threads = Array.from({ length: THREAD_COUNT }, (_, i) => {
    const d = ribbonThreadPathD(i, bundlePhase, muted, flowAngle);
    const dTrail = ribbonThreadPathD(i, bundlePhase, muted, flowAngle - TRAIL_PHASE);
    const { stroke, w } = strokeForThread(i, muted);
    return { i, d, dTrail, stroke, w };
  });

  const T = 2 * Math.PI;
  const kDirFor = (idx: number) => (idx % 2 === 0 ? 1 : -1) * (1 + (idx % 3));
  const drawOrder = Array.from({ length: THREAD_COUNT }, (_, idx) => idx).sort(
    (a, b) =>
      Math.sin((T * a) / THREAD_COUNT + flowAngle * kDirFor(a)) -
      Math.sin((T * b) / THREAD_COUNT + flowAngle * kDirFor(b)),
  );

  return (
    <svg
      viewBox={`0 0 ${THREAD_TILE} ${RIBBON_VB_H}`}
      preserveAspectRatio="none"
      className={className}
    >
      <defs>
        <filter id={`thread-glow${idSuffix}`} x="-18%" y="-18%" width="136%" height="136%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.9" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {drawOrder.map((idx) => {
        const t = threads[idx];
        return (
          <g key={t.i}>
            <path d={t.dTrail} fill="none" stroke={t.stroke} strokeWidth={t.w} strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.25" filter={`url(#thread-glow${idSuffix})`} />
            <path
              d={t.d}
              fill="none"
              stroke={t.stroke}
              strokeWidth={t.w}
              strokeLinecap="round"
              strokeLinejoin="round"
              filter={`url(#thread-glow${idSuffix})`}
            />
          </g>
        );
      })}
    </svg>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  /** Continuous flow angle (no % 2π) — trig wraps; avoids visible loop “reset”. Throttled setState. */
  return (
    <div className="relative min-h-screen overflow-hidden bg-transparent">
      <AnimatedBackground />

      {/* Content */}
      <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-7xl flex-col px-6 py-7 md:px-10 md:py-8">
        {/* Top bar */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="ml-auto w-fit"
        >
          <div className="hidden md:inline-flex items-center gap-3 rounded-full border border-black/10 bg-white/70 px-3 py-2 text-xs text-black/60 backdrop-blur">
            <span className="inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#0070AD] shadow-[0_0_0_4px_rgba(0,112,173,0.12)]" />
              AI-native data transformation suite
            </span>
            <span className="text-black/25">|</span>
            <span className="inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#0070AD]/90" />
              Secure by design
            </span>
            <span className="text-black/25">|</span>
            <span className="inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#12ABDB]/90" />
              Fast onboarding
            </span>
          </div>
        </motion.div>

        {/* Main hero */}
        <div className="flex flex-1 items-center py-7 md:py-10">
          <div className="grid w-full gap-8 lg:grid-cols-[1.12fr_0.88fr] lg:items-center">
            {/* Left: headline + actions */}
            <div className="flex flex-col text-center lg:text-left">
              <motion.h1
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.65, delay: 0.2, ease: 'easeOut' }}
                className="mt-4 text-4xl font-extrabold tracking-tight text-zinc-900 sm:text-5xl lg:text-6xl [font-family:Helvetica,Arial,sans-serif]"
              >
                <motion.span
                  className="group/logo inline-flex flex-col items-center justify-center gap-3 lg:items-start lg:justify-start cursor-default"
                  whileHover={{ scale: reduceMotion ? 1 : 1.02 }}
                  transition={{ duration: reduceMotion ? 0 : 0.2 }}
                >
                  <span className="relative inline-flex opacity-95">
                    <span className="pointer-events-none absolute -inset-3 rounded-xl blur-xl bg-[#0070AD]/20 opacity-0 transition-opacity duration-300 group-hover/logo:opacity-100" />
                    <SogetiLogo className="relative h-9 w-32 md:h-10 md:w-36 -translate-x-10 lg:-translate-x-8 transition-[filter] duration-300 group-hover/logo:drop-shadow-[0_0_24px_rgba(0,112,173,0.3)]" />
                  </span>
                  <span className="inline-flex flex-wrap items-center justify-center lg:justify-start gap-x-4">
                    <span>AGENT</span>
                    <span className="bg-gradient-to-r from-zinc-900 via-zinc-900 to-zinc-900/55 bg-clip-text text-transparent">
                      DHARA
                    </span>
                  </span>
                </motion.span>
              </motion.h1>

              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.42, ease: 'easeOut' }}
                className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start"
              >
                <motion.button
                  onClick={() => router.push('/auth/signup')}
                  whileHover={{ y: reduceMotion ? 0 : -2 }}
                  whileTap={{ scale: reduceMotion ? 1 : 0.98 }}
                  className="group relative inline-flex min-w-[180px] items-center justify-center gap-3 rounded-full border border-[#0070AD]/40 bg-transparent px-6 py-3 text-sm font-semibold text-[#0070AD] transition-all duration-300 hover:border-[#0070AD]/60 hover:bg-[#0070AD]/10 hover:text-[#0070AD] hover:shadow-[0_18px_60px_rgba(0,112,173,0.15)]"
                >
                  <span className="relative z-10 flex items-center gap-3">
                    Sign up
                    <FaRocket className="transition-transform duration-300 group-hover:translate-x-1 group-hover:rotate-12" />
                  </span>
                  <span className="absolute inset-0 rounded-full bg-gradient-to-r from-[#12ABDB]/20 via-[#0070AD]/20 to-[#12ABDB]/20 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                </motion.button>

                <motion.button
                  onClick={() => router.push('/auth/login')}
                  whileHover={{ y: reduceMotion ? 0 : -2 }}
                  whileTap={{ scale: reduceMotion ? 1 : 0.98 }}
                  className="group relative inline-flex min-w-[180px] items-center justify-center rounded-full border border-[#0070AD]/40 bg-transparent px-6 py-3 text-sm font-semibold text-[#0070AD] transition-all duration-300 hover:border-[#0070AD]/60 hover:bg-[#0070AD]/10 hover:text-[#0070AD] hover:shadow-[0_18px_60px_rgba(0,112,173,0.15)]"
                >
                  <span className="relative z-10">Login</span>
                  <span className="absolute inset-0 rounded-full bg-gradient-to-r from-[#12ABDB]/20 via-[#0070AD]/20 to-[#12ABDB]/20 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                </motion.button>
              </motion.div>

              {/* Supporting copy pinned to bottom of left column */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.55, delay: 0.55, ease: 'easeOut' }}
                className="mt-9 lg:mt-auto pt-7"
              >
                <div className="mt-5 flex flex-wrap justify-center gap-x-7 gap-y-2 text-sm text-black/60 lg:justify-start">
                  {['AI-Powered', 'Real-time profiling', 'Quality-first outputs'].map((t) => (
                    <span key={t} className="inline-flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-black/25" />
                      {t}
                    </span>
                  ))}
                </div>

                <p className="mx-auto mt-5 max-w-xl text-sm leading-relaxed text-black/60 lg:mx-0">
                  Intelligent Data Assessment, Quality & Transformation — designed for enterprise teams that need speed, trust, and repeatability.
                </p>

                <div className="mt-6 text-xs text-black/40">
                  © {new Date().getFullYear()} AGENT DHARA. Built by Sogeti.
                </div>
              </motion.div>
            </div>

            {/* Right: capabilities / preview */}
            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.25, ease: 'easeOut' }}
              className="relative"
            >
              <div className="relative overflow-hidden rounded-3xl border border-black/10 bg-white/70 p-5 backdrop-blur-xl">
                <div className="absolute inset-0 bg-gradient-to-br from-[#0070AD]/10 via-transparent to-[#12ABDB]/10" />

                <div className="relative">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-semibold text-zinc-900">What you can do</div>
                      <div className="mt-1 text-sm text-black/60">
                        From raw datasets to trusted, deployment-ready pipelines.
                      </div>
                    </div>
                    <div className="hidden sm:flex items-center gap-2 rounded-full border border-black/10 bg-white/75 px-3 py-1 text-xs text-black/60 animate-badge-pulse">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#0070AD]/90" />
                      Ready
                    </div>
                  </div>

                  <div className="mt-6 grid gap-3">
                    {[
                      { title: 'Assess', desc: 'Profile datasets, schemas, and outliers' },
                      { title: 'Validate', desc: 'Quality rules, anomalies, and drift' },
                      { title: 'Transform', desc: 'Generate consistent ETL-ready outputs' },
                      { title: 'Monitor', desc: 'Track health, SLAs, and outcomes' },
                    ].map((item, i) => (
                      <motion.div
                        key={item.title}
                        initial={{ opacity: 0, y: 16, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.45, delay: 0.5 + i * 0.12, ease: 'easeOut' }}
                        className="group/card relative rounded-2xl border border-black/10 bg-white/75 p-4 transition-all duration-300 hover:bg-white/90 hover:shadow-[0_0_30px_rgba(0,112,173,0.12)] hover:border-[#0070AD]/25"
                      >
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-gradient-to-br from-[#0070AD] to-[#12ABDB] shadow-[0_0_0_4px_rgba(0,112,173,0.10)]" />
                          <div className="min-w-0">
                            <div className="text-sm font-semibold text-zinc-900">{item.title}</div>
                            <div className="text-sm text-black/60">{item.desc}</div>
                          </div>
                        </div>
                        <div className="pointer-events-none absolute inset-0 rounded-2xl ring-1 ring-transparent transition group-hover/card:ring-white/10" />
                      </motion.div>
                    ))}
                  </div>

                  <div className="mt-6 flex items-center justify-between text-xs text-black/50">
                    <span>AGENT DHARA</span>
                    <span className="inline-flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#0070AD]/80" />
                      Live preview
                    </span>
                  </div>
                </div>
              </div>

              {/* Glow */}
              <div className="pointer-events-none absolute -inset-8 -z-10 bg-gradient-to-br from-[#0070AD]/20 via-transparent to-[#12ABDB]/20 blur-3xl" />
            </motion.div>
          </div>
        </div>

      </div>
    </div>
  );
}
