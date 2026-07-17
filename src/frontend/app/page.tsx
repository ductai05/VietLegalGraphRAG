"use client"

import React, { useRef, useEffect, useState, useCallback } from "react"
import { IntroAnimation, HERO_REVEAL_MS } from "@/components/intro-animation"
import { RevealText } from "@/components/reveal-text"
import { MobileNav } from "@/components/mobile-nav"

// ─── Intersection Observer hook ──────────────────────────────────────────────
function useInView(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setInView(true) }, { threshold })
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold])
  return { ref, inView }
}

// ─── Bento card ──────────────────────────────────────────────────────────────
function BentoCard({ children, className = "", delay = 0, dark = false }: { children: React.ReactNode; className?: string; delay?: number; dark?: boolean }) {
  const { ref, inView } = useInView(0.1)
  return (
    <div
      ref={ref}
      className={`group relative rounded-2xl border overflow-hidden transition-all duration-700 ${
        dark
          ? "border-white/[0.08] bg-[#0F2044] hover:bg-[#1A3260]"
          : "border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff]"
      } ${className}`}
      style={{
        opacity: inView ? 1 : 0,
        transform: inView ? "translateY(0)" : "translateY(28px)",
        transition: `opacity 0.7s ease ${delay}ms, transform 0.7s ease ${delay}ms, border-color 0.3s ease, background-color 0.3s ease`,
      }}
    >
      {children}
    </div>
  )
}

// ─── Pill tag ─────────────────────────────────────────────────────────────────
function Tag({ children, gold = false }: { children: React.ReactNode; gold?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans ${
      gold
        ? "text-[#C9A227] bg-[#C9A227]/10 border border-[#C9A227]/20"
        : "text-[#0F2044]/50 bg-[#0F2044]/[0.05]"
    }`}>
      {children}
    </span>
  )
}

// ─── Section divider ─────────────────────────────────────────────────────────
function SectionDivider() {
  return <div className="border-t border-[#0F2044]/[0.07]" />
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function VietLegalPage() {
  const [email, setEmail] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [heroReady, setHeroReady] = useState(false)
  const [videoReady, setVideoReady] = useState(false)

  const handleIntroDone = useCallback(() => {
    setHeroReady(true)
  }, [])

  useEffect(() => {
    const t = setTimeout(() => setVideoReady(true), HERO_REVEAL_MS)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className="bg-[#F2F3F7] text-[#0F2044] min-h-screen font-sans antialiased">

      {/* ── INTRO ANIMATION ───────────────────────────────────────────────── */}
      <IntroAnimation onDone={handleIntroDone} />

      {/* ── STICKY NAV ────────────────────────────────────────────────────── */}
      <MobileNav />

      {/* ── HERO ──────────────────────────────────────────────────────────── */}
      <section className="relative h-screen overflow-hidden">

        {/* Video background */}
        <video
          autoPlay
          loop
          muted
          playsInline
          className="absolute inset-0 w-full h-full object-cover z-0"
          src="https://hebbkx1anhila5yf.public.blob.vercel-storage.com/agentic-hero-9yW3wnTNMfn2U6lsVhTTZSJFEvAoSj.mp4"
          style={{
            transform: videoReady ? "scale(1.05)" : "scale(0.85)",
            transition: "transform 2s cubic-bezier(0.16, 1, 0.3, 1)",
            filter: "hue-rotate(195deg) saturate(0.6) brightness(0.55)",
          }}
        />

        {/* Navy overlay */}
        <div className="absolute inset-0 z-5 pointer-events-none" style={{ background: "rgba(15,32,68,0.45)" }} />

        {/* Progressive blur + gradient rising from bottom */}
        <div className="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style={{ height: "65%", background: "linear-gradient(to top, #F2F3F7 0%, #F2F3F7 18%, rgba(242,243,247,0.85) 35%, rgba(242,243,247,0.5) 55%, rgba(242,243,247,0.15) 75%, transparent 100%)" }} />
        <div className="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style={{ height: "20%", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)", maskImage: "linear-gradient(to top, black 0%, transparent 100%)", WebkitMaskImage: "linear-gradient(to top, black 0%, transparent 100%)" }} />
        <div className="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style={{ height: "38%", backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)", maskImage: "linear-gradient(to top, black 0%, transparent 100%)", WebkitMaskImage: "linear-gradient(to top, black 0%, transparent 100%)" }} />

        <div className="h-20" />

        {/* Hero content anchored to bottom-left */}
        <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col px-6 md:px-12 pb-14 max-w-4xl">
          {/* Eyebrow badge */}
          <div
            className="mb-5"
            style={{
              opacity: heroReady ? 1 : 0,
              transform: heroReady ? "translateY(0px)" : "translateY(16px)",
              transition: "opacity 0.8s cubic-bezier(0.16,1,0.3,1) 0ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) 0ms",
            }}
          >
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] tracking-widest border border-[#C9A227]/30 text-[#C9A227] bg-[#0F2044]/60" style={{ backdropFilter: "blur(8px)" }}>
              <span className="w-1.5 h-1.5 rounded-full bg-[#C9A227] animate-pulse" />
              TRỢ LÝ PHÁP LÝ AI ĐẦU TIÊN TẠI VIỆT NAM
            </span>
          </div>

          {/* Title */}
          <h1
            className="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-light text-[#0F2044] leading-[1.0] tracking-tight mb-10"
            style={{
              fontFamily: '"Inter", sans-serif',
              opacity: heroReady ? 1 : 0,
              filter: heroReady ? "blur(0px)" : "blur(24px)",
              transform: heroReady ? "translateY(0px)" : "translateY(32px)",
              transition: "opacity 1s cubic-bezier(0.16,1,0.3,1) 60ms, filter 1s cubic-bezier(0.16,1,0.3,1) 60ms, transform 1s cubic-bezier(0.16,1,0.3,1) 60ms",
            }}
          >
            Hiểu luật.<br />
            <span className="text-[#C9A227]">Không chỉ</span><br />
            tìm luật.
          </h1>

          {/* Stats */}
          <div className="flex gap-8 sm:gap-14">
            {[
              { value: "GraphRAG", label: "Công nghệ" },
              { value: "100%", label: "Trích dẫn nguồn" },
              { value: "Việt Nam", label: "Bối cảnh pháp lý" },
            ].map((stat, i) => (
              <div
                key={i}
                style={{
                  opacity: heroReady ? 1 : 0,
                  filter: heroReady ? "blur(0px)" : "blur(16px)",
                  transform: heroReady ? "translateY(0px)" : "translateY(20px)",
                  transition: `opacity 0.8s cubic-bezier(0.16,1,0.3,1) ${160 + i * 80}ms, filter 0.8s cubic-bezier(0.16,1,0.3,1) ${160 + i * 80}ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) ${160 + i * 80}ms`,
                }}
              >
                <div className="text-xl sm:text-2xl text-[#0F2044] font-medium tracking-tight">{stat.value}</div>
                <div className="text-[10px] text-[#0F2044]/45 tracking-widest uppercase mt-1">{stat.label}</div>
              </div>
            ))}
          </div>

          {/* CTA buttons */}
          <div
            className="mt-8 flex flex-wrap gap-3"
            style={{
              opacity: heroReady ? 1 : 0,
              transform: heroReady ? "translateY(0px)" : "translateY(16px)",
              transition: "opacity 0.8s cubic-bezier(0.16,1,0.3,1) 400ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) 400ms",
            }}
          >
            <a href="#contact" className="px-6 py-3 rounded-xl bg-[#0F2044] text-white text-sm font-medium tracking-wide hover:bg-[#1A3260] transition-colors">
              Dùng thử miễn phí
            </a>
            <a href="#contact" className="px-6 py-3 rounded-xl border border-[#0F2044]/20 text-[#0F2044] text-sm font-medium tracking-wide hover:border-[#0F2044]/40 hover:bg-[#0F2044]/[0.04] transition-all">
              Liên hệ chuyên gia
            </a>
          </div>
        </div>
      </section>

      {/* ── CHALLENGE ─────────────────────────────────────────────────────── */}
      <section id="solution" className="py-28 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <div className="mb-4"><Tag>THÁCH THỨC</Tag></div>
              <RevealText className="text-4xl md:text-5xl font-light tracking-tight leading-[1.1]">
                {"Khi pháp luật\nngày càng phức tạp."}
              </RevealText>
              <p className="mt-6 text-base text-[#0F2044]/55 leading-relaxed">
                Mỗi vấn đề pháp lý thường liên quan đến nhiều luật, nghị định, thông tư và văn bản hướng dẫn. Tra cứu thủ công tốn thời gian, dễ bỏ sót quy định liên quan và khó theo dõi các văn bản sửa đổi, bổ sung, thay thế.
              </p>
              <p className="mt-4 text-base text-[#0F2044]/55 leading-relaxed">
                Một kết luận không đầy đủ có thể dẫn đến quyết định thiếu chính xác.
              </p>
            </div>

            {/* Visual — problem diagram */}
            <div className="grid grid-cols-2 gap-3">
              {[
                { icon: "⚖", title: "Nhiều văn bản liên quan", desc: "Luật, nghị định, thông tư và văn bản hướng dẫn chồng chéo" },
                { icon: "🔗", title: "Quan hệ phức tạp", desc: "Sửa đổi, bổ sung và thay thế khó theo dõi" },
                { icon: "⏱", title: "Tốn thời gian", desc: "Tra cứu thủ công mất nhiều giờ cho mỗi vấn đề" },
                { icon: "🎯", title: "Dễ bỏ sót", desc: "Thiếu sót căn cứ pháp lý quan trọng trong kết luận" },
              ].map((item, i) => (
                <BentoCard key={i} className="p-6" delay={i * 60}>
                  <div className="text-2xl mb-3" role="img" aria-label={item.title}>{item.icon}</div>
                  <h3 className="text-sm font-medium text-[#0F2044] mb-2">{item.title}</h3>
                  <p className="text-xs text-[#0F2044]/45 leading-relaxed">{item.desc}</p>
                </BentoCard>
              ))}
            </div>
          </div>
        </div>
      </section>

      <SectionDivider />

      {/* ── SOLUTION ──────────────────────────────────────────────────────── */}
      <section className="py-28 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16 flex flex-col items-center">
            <div className="mb-4"><Tag gold>GIẢI PHÁP</Tag></div>
            <RevealText className="text-4xl md:text-5xl lg:text-6xl font-light tracking-tight leading-[1.05]">
              {"GraphRAG — Từ tìm kiếm\nđến hiểu toàn cảnh pháp lý."}
            </RevealText>
            <p className="mt-6 text-base text-[#0F2044]/50 leading-relaxed max-w-2xl">
              VietLegalGraphRAG ứng dụng công nghệ GraphRAG để xây dựng mạng lưới tri thức pháp luật, kết nối các quy định, văn bản và mối quan hệ thành một hệ thống thống nhất.
            </p>
          </div>

          {/* Graph visual card — full width */}
          <BentoCard dark className="p-10 mb-3 min-h-[240px] relative overflow-hidden">
            {/* Decorative node graph lines */}
            <svg className="absolute inset-0 w-full h-full opacity-10" viewBox="0 0 900 240" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
              <circle cx="450" cy="120" r="12" fill="#C9A227" />
              {[[180,60],[720,60],[180,180],[720,180],[90,120],[810,120],[450,30],[450,210]].map(([x,y],i) => (
                <g key={i}>
                  <line x1="450" y1="120" x2={x} y2={y} stroke="#C9A227" strokeWidth="1" />
                  <circle cx={x} cy={y} r="5" fill="#C9A227" />
                </g>
              ))}
            </svg>
            <div className="relative z-10 max-w-2xl">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#C9A227]/30 text-[#C9A227] text-[11px] tracking-widest mb-6">
                <span className="w-1.5 h-1.5 rounded-full bg-[#C9A227] animate-pulse" />
                KNOWLEDGE GRAPH
              </div>
              <h2 className="text-3xl md:text-4xl font-light text-white leading-[1.1] mb-4">
                Thay vì chỉ trả về danh sách kết quả, hệ thống giúp bạn thấy được toàn bộ bức tranh pháp lý.
              </h2>
              <p className="text-sm text-white/50 leading-relaxed">
                Luật liên quan, văn bản được tham chiếu, quy định sửa đổi và căn cứ pháp lý hỗ trợ mỗi kết luận.
              </p>
            </div>
          </BentoCard>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              { label: "Tìm kiếm ngữ nghĩa", desc: "Hiểu nghĩa của câu hỏi thay vì chỉ khớp từ khóa." },
              { label: "Đồ thị tri thức", desc: "Liên kết mạng lưới giữa luật, nghị định, thông tư và điều khoản." },
              { label: "Lý luận & Trích dẫn AI", desc: "Tổng hợp thông tin từ nhiều nguồn, cung cấp đầy đủ căn cứ pháp lý." },
            ].map((item, i) => (
              <BentoCard key={i} className="p-7" delay={i * 80}>
                <div className="w-8 h-8 rounded-lg bg-[#0F2044]/[0.06] flex items-center justify-center mb-5">
                  <span className="text-[#C9A227] text-sm font-semibold">0{i + 1}</span>
                </div>
                <h3 className="text-base font-medium text-[#0F2044] mb-2">{item.label}</h3>
                <p className="text-sm text-[#0F2044]/45 leading-relaxed">{item.desc}</p>
              </BentoCard>
            ))}
          </div>
        </div>
      </section>

      <SectionDivider />

      {/* ── TECHNOLOGY ────────────────────────────────────────────────────── */}
      <section id="technology" className="py-28 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="mb-16">
            <div className="mb-4"><Tag>CÔNG NGHỆ</Tag></div>
            <RevealText className="text-4xl md:text-5xl font-light tracking-tight leading-[1.05]">
              {"Công nghệ đằng sau\nmỗi câu trả lời."}
            </RevealText>
            <p className="mt-4 text-base text-[#0F2044]/50 leading-relaxed max-w-xl">
              AI được thiết kế đặc biệt cho nghiên cứu và phân tích pháp lý. Mỗi truy vấn được xử lý đồng thời qua nhiều lớp truy xuất và suy luận.
            </p>
          </div>

          <div className="grid grid-cols-12 gap-3">
            {/* Large card */}
            <BentoCard className="col-span-12 md:col-span-7 p-8 min-h-[260px]" delay={0}>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl border border-[#0F2044]/10 bg-[#0F2044]/[0.04] flex items-center justify-center">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><path d="m4.93 4.93 2.12 2.12M16.95 16.95l2.12 2.12M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12"/></svg>
                </div>
                <h3 className="text-xl font-medium text-[#0F2044]">Tìm kiếm ngữ nghĩa</h3>
              </div>
              <p className="text-sm text-[#0F2044]/50 leading-relaxed mb-6 max-w-md">
                Hiểu nghĩa của câu hỏi thay vì chỉ khớp từ khóa. AI sử dụng mô hình Embedding để tìm luật và văn bản liên quan, dù người dùng diễn đạt theo nhiều cách khác nhau.
              </p>
              {/* Simulated search UI */}
              <div className="rounded-xl border border-[#0F2044]/[0.08] bg-[#0F2044]/[0.02] p-4">
                <div className="flex items-center gap-3 mb-3">
                  <div className="flex-1 h-8 rounded-lg bg-white border border-[#0F2044]/[0.08] flex items-center px-3 gap-2">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="2" className="opacity-30" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                    <span className="text-xs text-[#0F2044]/35">Điều kiện thành lập công ty tại Việt Nam?</span>
                  </div>
                  <div className="w-8 h-8 rounded-lg bg-[#0F2044] flex items-center justify-center shrink-0">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4z"/></svg>
                  </div>
                </div>
                <div className="space-y-1.5">
                  {["Luật Doanh nghiệp 2020 — Điều 22, 23", "Nghị định 01/2021/NĐ-CP — Điều 5, 6", "Thông tư 01/2021/TT-BKHĐT"].map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] text-[#0F2044]/50 py-1">
                      <div className="w-1 h-1 rounded-full bg-[#C9A227] shrink-0" />
                      {r}
                    </div>
                  ))}
                </div>
              </div>
            </BentoCard>

            {/* Right column */}
            <div className="col-span-12 md:col-span-5 flex flex-col gap-3">
              <BentoCard className="p-7 flex-1" delay={80}>
                <div className="w-9 h-9 rounded-lg border border-[#0F2044]/10 flex items-center justify-center mb-5">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="1.5" aria-hidden="true"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                </div>
                <h3 className="text-base font-medium mb-2">Tìm kiếm từ khóa</h3>
                <p className="text-xs text-[#0F2044]/45 leading-relaxed">Khớp chính xác tên luật, số điều, thuật ngữ chuyên ngành, giúp giảm thiểu bỏ sót căn cứ pháp lý quan trọng.</p>
              </BentoCard>

              <BentoCard dark className="p-7 flex-1" delay={120}>
                <div className="w-9 h-9 rounded-lg border border-white/10 flex items-center justify-center mb-5">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                </div>
                <h3 className="text-base font-medium text-white mb-2">GraphRAG Knowledge Graph</h3>
                <p className="text-xs text-white/45 leading-relaxed">Tận dụng mạng lưới quan hệ giữa luật, nghị định, thông tư, điều khoản và sửa đổi để AI hiểu bối cảnh pháp lý.</p>
              </BentoCard>
            </div>

            {/* Bottom row */}
            <BentoCard className="col-span-12 p-8" delay={160}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
                <div>
                  <div className="w-9 h-9 rounded-lg border border-[#0F2044]/10 flex items-center justify-center mb-5">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                  </div>
                  <h3 className="text-lg font-medium mb-2">Lý luận &amp; Trích dẫn AI</h3>
                  <p className="text-sm text-[#0F2044]/45 leading-relaxed">Tổng hợp thông tin từ nhiều nguồn thành câu trả lời mạch lạc, đồng thời cung cấp đầy đủ căn cứ pháp lý và trích dẫn để người dùng dễ dàng kiểm chứng.</p>
                </div>
                <div className="rounded-xl bg-[#0F2044]/[0.03] border border-[#0F2044]/[0.07] p-5">
                  <div className="text-[10px] text-[#0F2044]/30 tracking-widest uppercase mb-3">Căn cứ pháp lý</div>
                  <div className="space-y-2">
                    {[
                      { doc: "Luật DN 2020", art: "Điều 22", rel: "Điều kiện thành lập" },
                      { doc: "NĐ 01/2021", art: "Điều 5", rel: "Hồ sơ đăng ký" },
                      { doc: "TT 01/2021", art: "Khoản 3", rel: "Trình tự thực hiện" },
                    ].map((c, i) => (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <div className="shrink-0 px-2 py-0.5 rounded bg-[#C9A227]/10 text-[#C9A227] text-[10px] font-medium">{c.doc}</div>
                        <span className="text-[#0F2044]/60 font-medium">{c.art}</span>
                        <span className="text-[#0F2044]/35 flex-1 truncate">{c.rel}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </BentoCard>
          </div>
        </div>
      </section>

      <SectionDivider />

      {/* ── CORE FEATURES ─────────────────────────────────────────────────── */}
      <section id="features" className="py-28 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-8 mb-16">
            <div>
              <div className="mb-4"><Tag>TÍNH NĂNG CỐT LÕI</Tag></div>
              <RevealText className="text-4xl md:text-5xl font-light tracking-tight leading-[1.05]">
                {"Không chỉ tìm luật,\nmà còn kết nối và giải thích."}
              </RevealText>
            </div>
            <p className="text-sm text-[#0F2044]/45 leading-relaxed max-w-xs">
              VietLegalGraphRAG tìm kiếm, kết nối, giải thích và chứng minh tại sao câu trả lời đó là đúng.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              {
                num: "01",
                title: "Tìm kiếm thông minh",
                desc: "Đặt câu hỏi bằng ngôn ngữ tự nhiên và nhận câu trả lời kèm căn cứ pháp lý rõ ràng.",
                icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
                delay: 0,
              },
              {
                num: "02",
                title: "Kết nối các quy định",
                desc: "Tự động phát hiện mối liên hệ giữa luật, nghị định, thông tư và các văn bản liên quan.",
                icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M9 6h6M15.5 15.5 9 9"/></svg>,
                delay: 80,
              },
              {
                num: "03",
                title: "Giải thích dựa trên bằng chứng",
                desc: "Mỗi kết luận được kèm theo trích dẫn rõ ràng, giúp kiểm chứng dễ dàng.",
                icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>,
                delay: 120,
              },
              {
                num: "04",
                title: "AI Chuyên biệt cho Luật Việt Nam",
                desc: "Được tối ưu hóa cho dữ liệu pháp luật Việt Nam, cho kết quả chính xác phù hợp với bối cảnh trong nước.",
                icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
                delay: 160,
              },
            ].map((f) => (
              <BentoCard key={f.num} className="p-8 flex gap-6" delay={f.delay}>
                <div className="shrink-0 w-10 h-10 rounded-xl border border-[#0F2044]/10 flex items-center justify-center text-[#C9A227]">
                  {f.icon}
                </div>
                <div>
                  <div className="text-[10px] font-pixel tracking-widest text-[#0F2044]/25 mb-2">{f.num}</div>
                  <h3 className="text-base font-medium text-[#0F2044] mb-2">{f.title}</h3>
                  <p className="text-sm text-[#0F2044]/45 leading-relaxed">{f.desc}</p>
                </div>
              </BentoCard>
            ))}
          </div>
        </div>
      </section>

      <SectionDivider />

      {/* ── TARGET AUDIENCE ───────────────────────────────────────────────── */}
      <section id="audience" className="py-28 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="mb-16 text-center flex flex-col items-center">
            <div className="mb-4"><Tag gold>ĐỐI TƯỢNG SỬ DỤNG</Tag></div>
            <RevealText className="text-4xl md:text-5xl font-light tracking-tight leading-[1.05]">
              {"Dành cho những người\ncần ra quyết định đúng đắn."}
            </RevealText>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              {
                title: "Luật sư & Chuyên gia pháp lý",
                desc: "Rút ngắn thời gian nghiên cứu văn bản, nhanh chóng xác định căn cứ pháp lý và nâng cao chất lượng tư vấn.",
                icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
                delay: 0,
              },
              {
                title: "Doanh nghiệp",
                desc: "Hỗ trợ rà soát quy định, đánh giá rủi ro pháp lý và nâng cao hiệu quả tuân thủ trong hoạt động kinh doanh.",
                icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
                delay: 80,
              },
              {
                title: "Người dân",
                desc: "Tiếp cận pháp luật dễ dàng hơn qua AI, nhận hướng dẫn dựa trên bằng chứng mà không mất nhiều thời gian tra cứu.",
                icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
                delay: 140,
              },
            ].map((a) => (
              <BentoCard key={a.title} dark className="p-8" delay={a.delay}>
                <div className="w-12 h-12 rounded-xl border border-white/10 flex items-center justify-center mb-6">
                  {a.icon}
                </div>
                <h3 className="text-lg font-medium text-white mb-3">{a.title}</h3>
                <p className="text-sm text-white/50 leading-relaxed">{a.desc}</p>
              </BentoCard>
            ))}
          </div>
        </div>
      </section>

      {/* ── MARQUEE ───────────────────────────────────────────────────────── */}
      <section className="py-0 border-t border-[#0F2044]/[0.06] overflow-hidden select-none">
        <div className="flex border-b border-[#0F2044]/[0.06]" style={{ animation: "marqueeLeft 32s linear infinite" }}>
          {[...Array(3)].map((_, rep) => (
            <div key={rep} className="flex shrink-0">
              {["Luật Doanh nghiệp", "Luật Đất đai", "Luật Lao động", "Luật Thuế", "Luật Hợp đồng", "Luật Sở hữu trí tuệ", "Luật Đầu tư", "Bộ luật Dân sự", "Luật Xây dựng", "Luật Bảo hiểm"].map((cap) => (
                <div key={cap} className="flex items-center gap-6 px-10 py-5 border-r border-[#0F2044]/[0.06] shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#C9A227]/60 shrink-0" />
                  <span className="text-sm text-[#0F2044]/45 whitespace-nowrap tracking-wide">{cap}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="flex" style={{ animation: "marqueeRight 26s linear infinite" }}>
          {[...Array(3)].map((_, rep) => (
            <div key={rep} className="flex shrink-0">
              {["Nghị định hướng dẫn", "Thông tư liên bộ", "Văn bản sửa đổi", "Hướng dẫn thi hành", "Quyết định hành chính", "Công văn giải thích", "Án lệ tham chiếu", "Luật Phá sản", "Luật Cạnh tranh", "Luật BHXH"].map((cap) => (
                <div key={cap} className="flex items-center gap-6 px-10 py-5 border-r border-[#0F2044]/[0.06] shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#0F2044]/20 shrink-0" />
                  <span className="text-sm text-[#0F2044]/30 whitespace-nowrap tracking-wide">{cap}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA / FOOTER ──────────────────────────────────────────────────── */}
      <section id="contact" className="relative py-32 px-6 md:px-12 lg:px-20 border-t border-[#0F2044]/[0.07] overflow-hidden">
        {/* Navy bg panel */}
        <div className="absolute inset-0 pointer-events-none" style={{ background: "linear-gradient(to bottom, transparent 0%, rgba(15,32,68,0.04) 100%)" }} />

        <div className="relative z-10 max-w-3xl mx-auto text-center">
          <div className="mb-6">
            <Tag gold>BẮT ĐẦU NGAY</Tag>
          </div>
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-light tracking-tight leading-[1.05] mb-6 text-[#0F2044]">
            Đưa nghiên cứu pháp lý<br />lên một tiêu chuẩn mới.
          </h2>
          <p className="text-base text-[#0F2044]/50 leading-relaxed mb-10 max-w-xl mx-auto">
            Khám phá cách AI và GraphRAG giúp bạn tiếp cận hệ thống pháp luật Việt Nam nhanh hơn, chính xác hơn và minh bạch hơn.
          </p>

          {!submitted ? (
            <form
              onSubmit={e => { e.preventDefault(); if (email) setSubmitted(true) }}
              className="flex flex-col sm:flex-row gap-2 max-w-md mx-auto mb-6"
            >
              <input
                type="email"
                placeholder="email@congty.vn"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                className="flex-1 bg-white border border-[#0F2044]/10 rounded-xl px-4 py-3 text-sm text-[#0F2044] placeholder:text-[#0F2044]/30 focus:outline-none focus:border-[#0F2044]/30 transition-colors"
              />
              <button
                type="submit"
                className="px-8 py-3 bg-[#0F2044] text-white text-sm rounded-xl hover:bg-[#1A3260] transition-colors tracking-wide font-medium"
              >
                DÙNG THỬ
              </button>
            </form>
          ) : (
            <div className="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-[#C9A227]/20 bg-[#C9A227]/5 text-[#C9A227] text-sm mb-6">
              <div className="w-1.5 h-1.5 rounded-full bg-[#C9A227]" />
              Chúng tôi sẽ liên hệ với bạn sớm nhất.
            </div>
          )}

          <div className="mt-4">
            <a href="#contact" className="inline-flex items-center gap-2 text-sm text-[#0F2044]/50 hover:text-[#0F2044] transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.6a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 3h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
              Liên hệ chuyên gia
            </a>
          </div>
        </div>
      </section>

      {/* ── FOOTER ────────────────────────────────────────────────────────── */}
      <footer className="py-10 px-6 md:px-12 lg:px-20 border-t border-[#0F2044]/[0.07]">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
          <span className="font-sans text-sm font-semibold text-[#0F2044]">
            VietLegal<span className="text-[#C9A227]">GraphRAG</span>
          </span>

          <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
            {[
              { label: "Giải pháp",  href: "#solution" },
              { label: "Công nghệ", href: "#technology" },
              { label: "Tính năng", href: "#features" },
              { label: "Đối tượng", href: "#audience" },
              { label: "Liên hệ",   href: "#contact" },
            ].map(l => (
              <a key={l.label} href={l.href} className="text-xs text-[#0F2044]/40 hover:text-[#0F2044]/80 transition-colors tracking-wide">{l.label}</a>
            ))}
          </div>

          <div className="flex items-center gap-6">
            {[
              { label: "Chính sách bảo mật", href: "#" },
              { label: "Điều khoản sử dụng", href: "#" },
              { label: "Tài liệu",            href: "#" },
            ].map(l => (
              <a key={l.label} href={l.href} className="text-xs text-[#0F2044]/25 hover:text-[#0F2044]/55 transition-colors">{l.label}</a>
            ))}
          </div>
        </div>
        <div className="max-w-6xl mx-auto mt-8 pt-6 border-t border-[#0F2044]/[0.05]">
          <span className="text-xs text-[#0F2044]/20">© 2026 VietLegalGraphRAG. Bảo lưu mọi quyền.</span>
        </div>
      </footer>
    </div>
  )
}
