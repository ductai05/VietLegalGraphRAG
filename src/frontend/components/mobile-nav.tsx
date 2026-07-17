"use client"

import { useState } from "react"

const NAV_LINKS = [
  { label: "Giải pháp",    href: "#solution" },
  { label: "Công nghệ",    href: "#technology" },
  { label: "Tính năng",    href: "#features" },
  { label: "Đối tượng",    href: "#audience" },
  { label: "Liên hệ",      href: "#contact" },
]

const NAV_STYLE = {
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  background: "rgba(242,243,247,0.85)",
  boxShadow: "0 8px 32px rgba(15,32,68,0.08), 0 2px 8px rgba(15,32,68,0.06)",
} as const

export function MobileNav() {
  const [open, setOpen] = useState(false)

  const close = () => setOpen(false)

  return (
    <div className="fixed top-4 inset-x-0 z-50 flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto w-full max-w-3xl">

        {/* Main bar */}
        <nav
          className="flex items-center justify-between px-5 py-3 rounded-2xl border border-black/[0.06]"
          style={NAV_STYLE}
        >
          <span className="font-sans text-sm font-semibold tracking-tight text-[#0F2044]">VietLegal<span className="text-[#C9A227]">GraphRAG</span></span>

          {/* Desktop links */}
          <div className="hidden md:flex items-center gap-7" style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}>
            {NAV_LINKS.map(l => (
              <a
                key={l.label}
                href={l.href}
                className="text-[11px] text-black/60 hover:text-black transition-colors duration-200 tracking-wide"
              >
                {l.label}
              </a>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <a href="#contact" className="text-[11px] px-4 py-2 rounded-xl bg-[#0F2044] text-white hover:bg-[#1A3260] transition-all duration-200 tracking-wide hidden md:block" style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}>
              THỬ MIỄN PHÍ
            </a>

            {/* Burger — mobile only */}
            <button
              onClick={() => setOpen(v => !v)}
              className="md:hidden flex flex-col justify-center items-center w-8 h-8 gap-[5px] rounded-lg hover:bg-black/[0.04] transition-colors"
              aria-label={open ? "Close menu" : "Open menu"}
            >
              <span
                className="block h-px bg-black/60 transition-all duration-300 origin-center"
                style={{
                  width: "18px",
                  transform: open ? "translateY(6px) rotate(45deg)" : "none",
                }}
              />
              <span
                className="block h-px bg-black/60 transition-all duration-300"
                style={{
                  width: "18px",
                  opacity: open ? 0 : 1,
                  transform: open ? "scaleX(0)" : "none",
                }}
              />
              <span
                className="block h-px bg-black/60 transition-all duration-300 origin-center"
                style={{
                  width: "18px",
                  transform: open ? "translateY(-6px) rotate(-45deg)" : "none",
                }}
              />
            </button>
          </div>
        </nav>

        {/* Mobile dropdown */}
        <div
          className="md:hidden mt-2 overflow-hidden transition-all duration-300 ease-in-out"
          style={{ maxHeight: open ? "320px" : "0px", opacity: open ? 1 : 0 }}
        >
          <div
            className="rounded-2xl border border-black/[0.06] px-2 py-2 flex flex-col"
            style={NAV_STYLE}
          >
            {NAV_LINKS.map(l => (
              <a
                key={l.label}
                href={l.href}
                onClick={close}
                className="px-4 py-3 text-sm text-black/60 hover:text-black hover:bg-black/[0.03] rounded-xl transition-colors tracking-wide"
                style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
              >
                {l.label}
              </a>
            ))}
            <div className="mt-1 px-2 pb-1">
              <a href="#contact" className="block w-full text-center text-[11px] px-4 py-2.5 rounded-xl bg-[#0F2044] text-white hover:bg-[#1A3260] transition-all duration-200 tracking-wide" style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}>
                THỬ MIỄN PHÍ
              </a>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
