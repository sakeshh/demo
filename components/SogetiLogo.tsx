'use client';

export default function SogetiLogo({ className = '' }: { className?: string }) {
  return (
    <div className={`relative ${className}`}>
      {/* Using a file in /public to keep rendering crisp and consistent */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/sogeti-logo-2018.svg"
        alt="Sogeti — Part of Capgemini"
        className="h-full w-full object-contain"
        draggable={false}
      />
    </div>
  );
}
