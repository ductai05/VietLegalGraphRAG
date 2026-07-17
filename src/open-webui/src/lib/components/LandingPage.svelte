<script lang="ts">
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import { user } from '$lib/stores';

  $: tryNowLink = $user ? '/' : '/auth';

  // --- INTRO ANIMATION SUB-COMPONENT CONFIG ---
  const LETTERS = ["V", "I", "E", "T", "L", "E", "G", "A", "L"];
  const LETTER_IN_STAGGER = 90;    // ms between each letter appearing
  const LETTER_IN_DUR = 700;       // duration of each letter appear transition
  const HOLD_DURATION = 300;       // hold fully visible before exit
  const LETTERS_IN_TOTAL = LETTER_IN_STAGGER * (LETTERS.length - 1) + LETTER_IN_DUR + HOLD_DURATION;

  const LETTER_OUT_STAGGER = 55;   // ms between each letter disappearing
  const LETTER_OUT_DUR = 450;      // duration of each letter fade out
  const LETTERS_OUT_TOTAL = LETTER_OUT_STAGGER * (LETTERS.length - 1) + LETTER_OUT_DUR;

  const CURTAIN_DELAY = LETTERS_IN_TOTAL + 100;
  const CURTAIN_DURATION = 1300;   // matches the CSS transition on the curtain div
  const ANIM_TOTAL = CURTAIN_DELAY + LETTERS_OUT_TOTAL + 1400;

  const HERO_REVEAL_MS = CURTAIN_DELAY + CURTAIN_DURATION - 150;

  let animPhase: 'idle' | 'in' | 'out' | 'done' = 'idle';
  let curtainUp = false;
  let heroReady = false;
  let videoReady = false;

  // --- MOBILE NAV LOGIC ---
  let navOpen = false;
  const NAV_LINKS = [
    { label: "Giải pháp",    href: "#solution" },
    { label: "Công nghệ",    href: "#technology" },
    { label: "Tính năng",    href: "#features" },
    { label: "Đối tượng",    href: "#audience" },
    { label: "Liên hệ",      href: "#contact" },
  ];

  // --- CONTACT FORM STATE ---
  let email = "";
  let submitted = false;

  onMount(() => {
    // Intro animation timeline
    const t0 = setTimeout(() => animPhase = "in", 80);
    const t1 = setTimeout(() => animPhase = "out", LETTERS_IN_TOTAL);
    const t2 = setTimeout(() => curtainUp = true, CURTAIN_DELAY);
    const t3 = setTimeout(() => heroReady = true, HERO_REVEAL_MS);
    const t4 = setTimeout(() => animPhase = "done", ANIM_TOTAL);

    // Video zoom transition timing
    const tVideo = setTimeout(() => videoReady = true, HERO_REVEAL_MS);

    return () => {
      clearTimeout(t0);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
      clearTimeout(tVideo);
    };
  });
</script>

<svelte:head>
  <style>
    /* Marquee animation classes */
    @keyframes marqueeLeft {
      0% { transform: translateX(0); }
      100% { transform: translateX(-33.33%); }
    }
    @keyframes marqueeRight {
      0% { transform: translateX(-33.33%); }
      100% { transform: translateX(0); }
    }

    .animate-marquee-left {
      animation: marqueeLeft 32s linear infinite;
    }
    .animate-marquee-right {
      animation: marqueeRight 26s linear infinite;
    }
  </style>
</svelte:head>

<div class="bg-[#F2F3F7] text-[#0F2044] min-h-screen font-sans antialiased relative z-[1]">

  <!-- ── INTRO ANIMATION ── -->
  {#if animPhase !== "done"}
    <div class="fixed inset-0 z-[100] pointer-events-none" aria-hidden="true">
      <!-- Retracting curtain -->
      <div
        class="absolute inset-x-0 top-0"
        style="bottom: {curtainUp ? '100%' : '0%'}; transition: {curtainUp ? 'bottom 1.3s cubic-bezier(0.76, 0, 0.24, 1)' : 'none'}; background: #f5f4f1;"
      />

      <!-- Staggered letters -->
      <div class="absolute inset-0 flex items-center justify-center">
        <div class="flex" style="gap: 0.06em;">
          {#each LETTERS as letter, i}
            {@const inDelay = i * LETTER_IN_STAGGER}
            {@const outDelay = i * LETTER_OUT_STAGGER}
            {@const isIdle = animPhase === "idle"}
            {@const isIn = animPhase === "in"}
            {@const isOut = animPhase === "out"}

            {@const opacity = isIdle ? 0 : isIn ? 1 : 0}
            {@const blurVal = isIdle ? 36 : isIn ? 0 : 24}
            {@const translateY = isIdle ? 48 : isIn ? 0 : -20}

            {@const transitionStr = isOut
              ? `opacity ${LETTER_OUT_DUR}ms cubic-bezier(0.4,0,1,1) ${outDelay}ms, filter ${LETTER_OUT_DUR}ms cubic-bezier(0.4,0,1,1) ${outDelay}ms, transform ${LETTER_OUT_DUR}ms cubic-bezier(0.4,0,1,1) ${outDelay}ms`
              : isIn
              ? `opacity ${LETTER_IN_DUR}ms cubic-bezier(0.16,1,0.3,1) ${inDelay}ms, filter ${LETTER_IN_DUR}ms cubic-bezier(0.16,1,0.3,1) ${inDelay}ms, transform ${LETTER_IN_DUR}ms cubic-bezier(0.16,1,0.3,1) ${inDelay}ms`
              : "none"}

            <span
              class="font-sans font-bold text-[#111] leading-none select-none"
              style="font-size: calc((100vw - 64px) / {LETTERS.length}); letter-spacing: 0.05em; opacity: {opacity}; filter: blur({blurVal}px); transform: translateY({translateY}px); transition: {transitionStr}; will-change: opacity, filter, transform;"
            >
              {letter}
            </span>
          {/each}
        </div>
      </div>
    </div>
  {/if}

  <!-- ── STICKY NAV ── -->
  <div class="fixed top-4 inset-x-0 z-50 flex justify-center px-4 pointer-events-none">
    <div class="pointer-events-auto w-full max-w-3xl">
      <!-- Main bar -->
      <nav
        class="flex items-center justify-between px-5 py-3 rounded-2xl border border-black/[0.06] backdrop-blur-[16px] bg-[#F2F3F7]/85 shadow-[0_8px_32px_rgba(15,32,68,0.08),_0_2px_8px_rgba(15,32,68,0.06)]"
      >
        <span class="font-sans text-sm font-semibold tracking-tight text-[#0F2044]">
          VietLegal<span class="text-[#C9A227]">GraphRAG</span>
        </span>

        <!-- Desktop links -->
        <div class="hidden md:flex items-center gap-7 font-sans">
          {#each NAV_LINKS as l}
            <a
              href={l.href}
              class="text-[11px] text-[#0F2044]/60 hover:text-[#0F2044] transition-colors duration-200 tracking-wide font-medium"
            >
              {l.label}
            </a>
          {/each}
        </div>

        <div class="flex items-center gap-2">
          <a
            href={tryNowLink}
            class="text-[11px] px-4 py-2 rounded-xl bg-[#0F2044] text-white hover:bg-[#1A3260] transition-all duration-200 tracking-wide hidden md:block font-medium font-sans"
          >
            DÙNG THỬ
          </a>

          <!-- Burger — mobile only -->
          <button
            on:click={() => navOpen = !navOpen}
            class="md:hidden flex flex-col justify-center items-center w-8 h-8 gap-[5px] rounded-lg hover:bg-[#0F2044]/[0.04] transition-colors"
            aria-label={navOpen ? "Close menu" : "Open menu"}
          >
            <span
              class="block h-px bg-[#0F2044]/60 transition-all duration-300 origin-center"
              style="width: 18px; transform: {navOpen ? 'translateY(6px) rotate(45deg)' : 'none'};"
            />
            <span
              class="block h-px bg-[#0F2044]/60 transition-all duration-300"
              style="width: 18px; opacity: {navOpen ? 0 : 1}; transform: {navOpen ? 'scaleX(0)' : 'none'};"
            />
            <span
              class="block h-px bg-[#0F2044]/60 transition-all duration-300 origin-center"
              style="width: 18px; transform: {navOpen ? 'translateY(-6px) rotate(-45deg)' : 'none'};"
            />
          </button>
        </div>
      </nav>

      <!-- Mobile dropdown -->
      {#if navOpen}
        <div
          class="md:hidden mt-2 overflow-hidden transition-all duration-300 ease-in-out"
          style="max-height: 320px; opacity: 1;"
        >
          <div
            class="rounded-2xl border border-black/[0.06] px-2 py-2 flex flex-col backdrop-blur-[16px] bg-[#F2F3F7]/85 shadow-[0_8px_32px_rgba(15,32,68,0.08),_0_2px_8px_rgba(15,32,68,0.06)]"
          >
            {#each NAV_LINKS as l}
              <a
                href={l.href}
                on:click={() => navOpen = false}
                class="px-4 py-3 text-sm text-[#0F2044]/60 hover:text-[#0F2044] hover:bg-[#0F2044]/[0.03] rounded-xl transition-colors tracking-wide font-sans font-medium"
              >
                {l.label}
              </a>
            {/each}
            <div class="mt-1 px-2 pb-1">
              <a
                href={tryNowLink}
                class="block w-full text-center text-[11px] px-4 py-2.5 rounded-xl bg-[#0F2044] text-white hover:bg-[#1A3260] transition-all duration-200 tracking-wide font-sans font-medium"
              >
                DÙNG THỬ
              </a>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>

  <!-- ── HERO ── -->
  <section class="relative h-screen overflow-hidden">
    <!-- Video background -->
    <video
      autoPlay
      loop
      muted
      playsInline
      class="absolute inset-0 w-full h-full object-cover z-0"
      src="https://hebbkx1anhila5yf.public.blob.vercel-storage.com/agentic-hero-9yW3wnTNMfn2U6lsVhTTZSJFEvAoSj.mp4"
      style="transform: {videoReady ? 'scale(1.05)' : 'scale(0.85)'}; transition: transform 2s cubic-bezier(0.16, 1, 0.3, 1); filter: hue-rotate(195deg) saturate(0.6) brightness(0.55);"
    />

    <!-- Navy overlay -->
    <div class="absolute inset-0 z-5 pointer-events-none bg-[rgba(15,32,68,0.45)]" />

    <!-- Progressive blur + gradient rising from bottom -->
    <div class="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style="height: 65%; background: linear-gradient(to top, #F2F3F7 0%, #F2F3F7 18%, rgba(242,243,247,0.85) 35%, rgba(242,243,247,0.5) 55%, rgba(242,243,247,0.15) 75%, transparent 100%);" />
    <div class="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style="height: 20%; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); mask-image: linear-gradient(to top, black 0%, transparent 100%); -webkit-mask-image: linear-gradient(to top, black 0%, transparent 100%);" />
    <div class="absolute inset-x-0 bottom-0 z-10 pointer-events-none" style="height: 38%; backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); mask-image: linear-gradient(to top, black 0%, transparent 100%); -webkit-mask-image: linear-gradient(to top, black 0%, transparent 100%);" />

    <div class="h-20" />

    <!-- Hero content anchored to bottom-left -->
    <div class="absolute inset-x-0 bottom-0 z-30 flex flex-col px-6 md:px-12 pb-14 max-w-4xl">
      <!-- Eyebrow badge -->
      <div
        class="mb-5"
        style="opacity: {heroReady ? 1 : 0}; transform: {heroReady ? 'translateY(0px)' : 'translateY(16px)'}; transition: opacity 0.8s cubic-bezier(0.16,1,0.3,1) 0ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) 0ms;"
      >
        <span class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] tracking-widest border border-[#C9A227]/30 text-[#C9A227] bg-[#0F2044]/60 backdrop-blur-[8px]">
          <span class="w-1.5 h-1.5 rounded-full bg-[#C9A227] animate-pulse" />
          TRỢ LÝ PHÁP LÝ AI ĐẦU TIÊN TẠI VIỆT NAM
        </span>
      </div>

      <!-- Title -->
      <h1
        class="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-light text-[#0F2044] leading-[1.0] tracking-tight mb-10 font-sans"
        style="opacity: {heroReady ? 1 : 0}; filter: {heroReady ? 'blur(0px)' : 'blur(24px)'}; transform: {heroReady ? 'translateY(0px)' : 'translateY(32px)'}; transition: opacity 1s cubic-bezier(0.16,1,0.3,1) 60ms, filter 1s cubic-bezier(0.16,1,0.3,1) 60ms, transform 1s cubic-bezier(0.16,1,0.3,1) 60ms;"
      >
        Hiểu luật.<br />
        <span class="text-[#C9A227]">Không chỉ</span><br />
        tìm luật.
      </h1>

      <!-- Stats -->
      <div class="flex gap-8 sm:gap-14">
        {#each [
          { value: "GraphRAG", label: "Công nghệ" },
          { value: "100%", label: "Trích dẫn nguồn" },
          { value: "Việt Nam", label: "Bối cảnh pháp lý" }
        ] as stat, i}
          <div
            style="opacity: {heroReady ? 1 : 0}; filter: {heroReady ? 'blur(0px)' : 'blur(16px)'}; transform: {heroReady ? 'translateY(0px)' : 'translateY(20px)'}; transition: opacity 0.8s cubic-bezier(0.16,1,0.3,1) {160 + i * 80}ms, filter 0.8s cubic-bezier(0.16,1,0.3,1) {160 + i * 80}ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) {160 + i * 80}ms;"
          >
            <div class="text-xl sm:text-2xl text-[#0F2044] font-medium tracking-tight">{stat.value}</div>
            <div class="text-[10px] text-[#0F2044]/45 tracking-widest uppercase mt-1">{stat.label}</div>
          </div>
        {/each}
      </div>

      <!-- CTA buttons -->
      <div
        class="mt-8 flex flex-wrap gap-3"
        style="opacity: {heroReady ? 1 : 0}; transform: {heroReady ? 'translateY(0px)' : 'translateY(16px)'}; transition: opacity 0.8s cubic-bezier(0.16,1,0.3,1) 400ms, transform 0.8s cubic-bezier(0.16,1,0.3,1) 400ms;"
      >
        <a href={tryNowLink} class="px-6 py-3 rounded-xl bg-[#0F2044] text-white text-sm font-medium tracking-wide hover:bg-[#1A3260] transition-colors">
          Dùng thử miễn phí
        </a>
        <a href="#contact" class="px-6 py-3 rounded-xl border border-[#0F2044]/20 text-[#0F2044] text-sm font-medium tracking-wide hover:border-[#0F2044]/40 hover:bg-[#0F2044]/[0.04] transition-all">
          Liên hệ chuyên gia
        </a>
      </div>
    </div>
  </section>

  <!-- ── CHALLENGE ── -->
  <section id="solution" class="py-28 px-6 md:px-12 lg:px-20">
    <div class="max-w-6xl mx-auto">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
        <div>
          <div class="mb-4">
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#0F2044]/50 bg-[#0F2044]/[0.05]">THÁCH THỨC</span>
          </div>
          <h2 class="text-4xl md:text-5xl font-light tracking-tight leading-[1.1]">
            Khi pháp luật ngày càng phức tạp.
          </h2>
          <p class="mt-6 text-base text-[#0F2044]/55 leading-relaxed">
            Mỗi vấn đề pháp lý thường liên quan đến nhiều luật, nghị định, thông tư và văn bản hướng dẫn. Tra cứu thủ công tốn thời gian, dễ bỏ sót quy định liên quan và khó theo dõi các văn bản sửa đổi, bổ sung, thay thế.
          </p>
          <p class="mt-4 text-base text-[#0F2044]/55 leading-relaxed">
            Một kết luận không đầy đủ có thể dẫn đến quyết định thiếu chính xác.
          </p>
        </div>

        <!-- Bento Grid problem details -->
        <div class="grid grid-cols-2 gap-3">
          {#each [
            { icon: "⚖", title: "Nhiều văn bản liên quan", desc: "Luật, nghị định, thông tư và văn bản hướng dẫn chồng chéo" },
            { icon: "🔗", title: "Quan hệ phức tạp", desc: "Sửa đổi, bổ sung và thay thế khó theo dõi" },
            { icon: "⏱", title: "Tốn thời gian", desc: "Tra cứu thủ công mất nhiều giờ cho mỗi vấn đề" },
            { icon: "🎯", title: "Dễ bỏ sót", desc: "Thiếu sót căn cứ pháp lý quan trọng trong kết luận" }
          ] as item}
            <div
              class="group relative rounded-2xl border overflow-hidden p-6 transition-all duration-700 border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff]"
            >
              <div class="text-2xl mb-3" role="img" aria-label={item.title}>{item.icon}</div>
              <h3 class="text-sm font-medium text-[#0F2044] mb-2">{item.title}</h3>
              <p class="text-xs text-[#0F2044]/45 leading-relaxed">{item.desc}</p>
            </div>
          {/each}
        </div>
      </div>
    </div>
  </section>

  <hr class="border-t border-[#0F2044]/[0.07]" />

  <!-- ── SOLUTION ── -->
  <section class="py-28 px-6 md:px-12 lg:px-20">
    <div class="max-w-6xl mx-auto">
      <div class="text-center mb-16 flex flex-col items-center">
        <div class="mb-4">
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#C9A227] bg-[#C9A227]/10 border border-[#C9A227]/20">GIẢI PHÁP</span>
        </div>
        <h2 class="text-4xl md:text-5xl lg:text-6xl font-light tracking-tight leading-[1.05]">
          GraphRAG — Từ tìm kiếm<br />đến hiểu toàn cảnh pháp lý.
        </h2>
        <p class="mt-6 text-base text-[#0F2044]/50 leading-relaxed max-w-2xl">
          VietLegalGraphRAG ứng dụng công nghệ GraphRAG để xây dựng mạng lưới tri thức pháp luật, kết nối các quy định, văn bản và mối quan hệ thành một hệ thống thống nhất.
        </p>
      </div>

      <!-- Graph visual card — full width -->
      <div
        class="group relative rounded-2xl border overflow-hidden p-10 mb-3 min-h-[240px] border-white/[0.08] bg-[#0F2044] hover:bg-[#1A3260] transition-all duration-700"
      >
        <!-- Decorative node graph lines -->
        <svg class="absolute inset-0 w-full h-full opacity-10" viewBox="0 0 900 240" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <circle cx="450" cy="120" r="12" fill="#C9A227" />
          {#each [[180,60],[720,60],[180,180],[720,180],[90,120],[810,120],[450,30],[450,210]] as [x,y]}
            <g>
              <line x1="450" y1="120" x2={x} y2={y} stroke="#C9A227" strokeWidth="1" />
              <circle cx={x} cy={y} r="5" fill="#C9A227" />
            </g>
          {/each}
        </svg>
        <div class="relative z-10 max-w-2xl">
          <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#C9A227]/30 text-[#C9A227] text-[11px] tracking-widest mb-6">
            <span class="w-1.5 h-1.5 rounded-full bg-[#C9A227] animate-pulse" />
            KNOWLEDGE GRAPH
          </div>
          <h2 class="text-3xl md:text-4xl font-light text-white leading-[1.1] mb-4 font-sans">
            Thay vì chỉ trả về danh sách kết quả, hệ thống giúp bạn thấy được toàn bộ bức tranh pháp lý.
          </h2>
          <p class="text-sm text-white/50 leading-relaxed">
            Luật liên quan, văn bản được tham chiếu, quy định sửa đổi và căn cứ pháp lý hỗ trợ mỗi kết luận.
          </p>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        {#each [
          { label: "Tìm kiếm ngữ nghĩa", desc: "Hiểu nghĩa của câu hỏi thay vì chỉ khớp từ khóa." },
          { label: "Đồ thị tri thức", desc: "Liên kết mạng lưới giữa luật, nghị định, thông tư và điều khoản." },
          { label: "Lý luận & Trích dẫn AI", desc: "Tổng hợp thông tin từ nhiều nguồn, cung cấp đầy đủ căn cứ pháp lý." }
        ] as item, i}
          <div
            class="group relative rounded-2xl border overflow-hidden p-7 border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff] transition-all duration-700"
          >
            <div class="w-8 h-8 rounded-lg bg-[#0F2044]/[0.06] flex items-center justify-center mb-5">
              <span class="text-[#C9A227] text-sm font-semibold">0{i + 1}</span>
            </div>
            <h3 class="text-base font-medium text-[#0F2044] mb-2">{item.label}</h3>
            <p class="text-sm text-[#0F2044]/45 leading-relaxed">{item.desc}</p>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <hr class="border-t border-[#0F2044]/[0.07]" />

  <!-- ── TECHNOLOGY ── -->
  <section id="technology" class="py-28 px-6 md:px-12 lg:px-20">
    <div class="max-w-6xl mx-auto">
      <div class="mb-16">
        <div class="mb-4">
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#0F2044]/50 bg-[#0F2044]/[0.05]">CÔNG NGHỆ</span>
        </div>
        <h2 class="text-4xl md:text-5xl font-light tracking-tight leading-[1.05] font-sans">
          Công nghệ đằng sau<br />mỗi câu trả lời.
        </h2>
        <p class="mt-4 text-base text-[#0F2044]/50 leading-relaxed max-w-xl">
          AI được thiết kế đặc biệt cho nghiên cứu và phân tích pháp lý. Mỗi truy vấn được xử lý đồng thời qua nhiều lớp truy xuất và suy luận.
        </p>
      </div>

      <div class="grid grid-cols-12 gap-3">
        <!-- Large card -->
        <div
          class="col-span-12 md:col-span-7 group relative rounded-2xl border overflow-hidden p-8 min-h-[260px] border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff] transition-all duration-700"
        >
          <div class="flex items-center gap-3 mb-6">
            <div class="w-10 h-10 rounded-xl border border-[#0F2044]/10 bg-[#0F2044]/[0.04] flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><path d="m4.93 4.93 2.12 2.12M16.95 16.95l2.12 2.12M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12"/></svg>
            </div>
            <h3 class="text-xl font-medium text-[#0F2044]">Tìm kiếm ngữ nghĩa</h3>
          </div>
          <p class="text-sm text-[#0F2044]/50 leading-relaxed mb-6 max-w-md">
            Hiểu nghĩa của câu hỏi thay vì chỉ khớp từ khóa. AI sử dụng mô hình Embedding để tìm luật và văn bản liên quan, dù người dùng diễn đạt theo nhiều cách khác nhau.
          </p>
          <!-- Simulated search UI -->
          <div class="rounded-xl border border-[#0F2044]/[0.08] bg-[#0F2044]/[0.02] p-4">
            <div class="flex items-center gap-3 mb-3">
              <div class="flex-1 h-8 rounded-lg bg-white border border-[#0F2044]/[0.08] flex items-center px-3 gap-2">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="2" class="opacity-30" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <span class="text-xs text-[#0F2044]/35">Điều kiện thành lập công ty tại Việt Nam?</span>
              </div>
              <div class="w-8 h-8 rounded-lg bg-[#0F2044] flex items-center justify-center shrink-0">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4z"/></svg>
              </div>
            </div>
            <div class="space-y-1.5">
              {#each ["Luật Doanh nghiệp 2020 — Điều 22, 23", "Nghị định 01/2021/NĐ-CP — Điều 5, 6", "Thông tư 01/2021/TT-BKHĐT"] as r}
                <div class="flex items-center gap-2 text-[10px] text-[#0F2044]/50 py-1">
                  <div class="w-1 h-1 rounded-full bg-[#C9A227] shrink-0" />
                  {r}
                </div>
              {/each}
            </div>
          </div>
        </div>

        <!-- Right column -->
        <div class="col-span-12 md:col-span-5 flex flex-col gap-3">
          <div
            class="group relative rounded-2xl border overflow-hidden p-7 border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff] transition-all duration-700 flex-1"
          >
            <div class="w-9 h-9 rounded-lg border border-[#0F2044]/10 flex items-center justify-center mb-5">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0F2044" strokeWidth="1.5" aria-hidden="true"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <h3 class="text-base font-medium mb-2">Tìm kiếm từ khóa</h3>
            <p class="text-xs text-[#0F2044]/45 leading-relaxed">Khớp chính xác tên luật, số điều, thuật ngữ chuyên ngành, giúp giảm thiểu bỏ sót căn cứ pháp lý quan trọng.</p>
          </div>

          <div
            class="group relative rounded-2xl border overflow-hidden p-7 border-white/[0.08] bg-[#0F2044] hover:bg-[#1A3260] transition-all duration-700 flex-1"
          >
            <div class="w-9 h-9 rounded-lg border border-white/10 flex items-center justify-center mb-5">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
            </div>
            <h3 class="text-base font-medium text-white mb-2 font-sans">GraphRAG Knowledge Graph</h3>
            <p class="text-xs text-white/45 leading-relaxed">Tận dụng mạng lưới quan hệ giữa luật, nghị định, thông tư, điều khoản và sửa đổi để AI hiểu bối cảnh pháp lý.</p>
          </div>
        </div>

        <!-- Bottom row -->
        <div
          class="col-span-12 group relative rounded-2xl border overflow-hidden p-8 border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff] transition-all duration-700"
        >
          <div class="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
            <div>
              <div class="w-9 h-9 rounded-lg border border-[#0F2044]/10 flex items-center justify-center mb-5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C9A227" strokeWidth="1.5" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
              </div>
              <h3 class="text-lg font-medium mb-2">Lý luận &amp; Trích dẫn AI</h3>
              <p class="text-sm text-[#0F2044]/45 leading-relaxed">Tổng hợp thông tin từ nhiều nguồn thành câu trả lời mạch lạc, đồng thời cung cấp đầy đủ căn cứ pháp lý và trích dẫn để người dùng dễ dàng kiểm chứng.</p>
            </div>
            <div class="rounded-xl bg-[#0F2044]/[0.03] border border-[#0F2044]/[0.07] p-5">
              <div class="text-[10px] text-[#0F2044]/30 tracking-widest uppercase mb-3">Căn cứ pháp lý</div>
              <div class="space-y-2">
                {#each [
                  { doc: "Luật DN 2020", art: "Điều 22", rel: "Điều kiện thành lập" },
                  { doc: "NĐ 01/2021", art: "Điều 5", rel: "Hồ sơ đăng ký" },
                  { doc: "TT 01/2021", art: "Khoản 3", rel: "Trình tự thực hiện" }
                ] as c}
                  <div class="flex items-center gap-3 text-xs">
                    <div class="shrink-0 px-2 py-0.5 rounded bg-[#C9A227]/10 text-[#C9A227] text-[10px] font-medium">{c.doc}</div>
                    <span class="text-[#0F2044]/60 font-medium">{c.art}</span>
                    <span class="text-[#0F2044]/35 flex-1 truncate">{c.rel}</span>
                  </div>
                {/each}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <hr class="border-t border-[#0F2044]/[0.07]" />

  <!-- ── CORE FEATURES ── -->
  <section id="features" class="py-28 px-6 md:px-12 lg:px-20">
    <div class="max-w-6xl mx-auto">
      <div class="flex flex-col md:flex-row md:items-end md:justify-between gap-8 mb-16">
        <div>
          <div class="mb-4">
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#0F2044]/50 bg-[#0F2044]/[0.05]">TÍNH NĂNG CỐT LÕI</span>
          </div>
          <h2 class="text-4xl md:text-5xl font-light tracking-tight leading-[1.05] font-sans">
            Không chỉ tìm luật,<br />mà còn kết nối và giải thích.
          </h2>
        </div>
        <p class="text-sm text-[#0F2044]/45 leading-relaxed max-w-xs">
          VietLegalGraphRAG tìm kiếm, kết nối, giải thích và chứng minh tại sao câu trả lời đó là đúng.
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        {#each [
          {
            num: "01",
            title: "Tìm kiếm thông minh",
            desc: "Đặt câu hỏi bằng ngôn ngữ tự nhiên và nhận câu trả lời kèm căn cứ pháp lý rõ ràng.",
            icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`,
            delay: 0
          },
          {
            num: "02",
            title: "Kết nối các quy định",
            desc: "Tự động phát hiện mối liên hệ giữa luật, nghị định, thông tư và các văn bản liên quan.",
            icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M9 6h6M15.5 15.5 9 9"/></svg>`,
            delay: 80
          },
          {
            num: "03",
            title: "Giải thích dựa trên bằng chứng",
            desc: "Mỗi kết luận được kèm theo trích dẫn rõ ràng, giúp kiểm chứng dễ dàng.",
            icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
            delay: 120
          },
          {
            num: "04",
            title: "AI Chuyên biệt cho Luật Việt Nam",
            desc: "Được tối ưu hóa cho dữ liệu pháp luật Việt Nam, cho kết quả chính xác phù hợp với bối cảnh trong nước.",
            icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
            delay: 160
          }
        ] as f}
          <div
            class="group relative rounded-2xl border overflow-hidden p-8 flex gap-6 border-[#0F2044]/[0.08] bg-white hover:border-[#0F2044]/[0.15] hover:bg-[#fafbff] transition-all duration-700"
          >
            <div class="shrink-0 w-10 h-10 rounded-xl border border-[#0F2044]/10 flex items-center justify-center text-[#C9A227]">
              {@html f.icon}
            </div>
            <div>
              <div class="text-[10px] tracking-widest text-[#0F2044]/25 mb-2">{f.num}</div>
              <h3 class="text-base font-medium text-[#0F2044] mb-2">{f.title}</h3>
              <p class="text-sm text-[#0F2044]/45 leading-relaxed">{f.desc}</p>
            </div>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <hr class="border-t border-[#0F2044]/[0.07]" />

  <!-- ── TARGET AUDIENCE ── -->
  <section id="audience" class="py-28 px-6 md:px-12 lg:px-20">
    <div class="max-w-6xl mx-auto">
      <div class="mb-16 text-center flex flex-col items-center">
        <div class="mb-4">
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#C9A227] bg-[#C9A227]/10 border border-[#C9A227]/20">ĐỐI TƯỢNG SỬ DỤNG</span>
        </div>
        <h2 class="text-4xl md:text-5xl font-light tracking-tight leading-[1.05] font-sans">
          Dành cho những người<br />cần ra quyết định đúng đắn.
        </h2>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        {#each [
          {
            title: "Luật sư & Chuyên gia pháp lý",
            desc: "Rút ngắn thời gian nghiên cứu văn bản, nhanh chóng xác định căn cứ pháp lý và nâng cao chất lượng tư vấn.",
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
            delay: 0
          },
          {
            title: "Doanh nghiệp",
            desc: "Hỗ trợ rà soát quy định, đánh giá rủi ro pháp lý và nâng cao hiệu quả tuân thủ trong hoạt động kinh doanh.",
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" stroke-width="1.5"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
            delay: 80
          },
          {
            title: "Người dân",
            desc: "Tiếp cận pháp luật dễ dàng hơn qua AI, nhận hướng dẫn dựa trên bằng chứng mà không mất nhiều thời gian tra cứu.",
            icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9A227" stroke-width="1.5"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
            delay: 140
          }
        ] as a}
          <div
            class="group relative rounded-2xl border overflow-hidden p-8 border-white/[0.08] bg-[#0F2044] hover:bg-[#1A3260] transition-all duration-700"
          >
            <div class="w-12 h-12 rounded-xl border border-white/10 flex items-center justify-center mb-6">
              {@html a.icon}
            </div>
            <h3 class="text-lg font-medium text-white mb-3 font-sans">{a.title}</h3>
            <p class="text-sm text-white/50 leading-relaxed">{a.desc}</p>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <!-- ── MARQUEE ── -->
  <section class="py-0 border-t border-[#0F2044]/[0.06] overflow-hidden select-none">
    <!-- Left marquee -->
    <div class="flex border-b border-[#0F2044]/[0.06] animate-marquee-left">
      {#each [1, 2, 3] as rep}
        <div class="flex shrink-0">
          {#each ["Luật Doanh nghiệp", "Luật Đất đai", "Luật Lao động", "Luật Thuế", "Luật Hợp đồng", "Luật Sở hữu trí tuệ", "Luật Đầu tư", "Bộ luật Dân sự", "Luật Xây dựng", "Luật Bảo hiểm"] as cap}
            <div class="flex items-center gap-6 px-10 py-5 border-r border-[#0F2044]/[0.06] shrink-0">
              <span class="w-1.5 h-1.5 rounded-full bg-[#C9A227]/60 shrink-0" />
              <span class="text-sm text-[#0F2044]/45 whitespace-nowrap tracking-wide font-sans">{cap}</span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
    <!-- Right marquee -->
    <div class="flex animate-marquee-right">
      {#each [1, 2, 3] as rep}
        <div class="flex shrink-0">
          {#each ["Nghị định hướng dẫn", "Thông tư liên bộ", "Văn bản sửa đổi", "Hướng dẫn thi hành", "Quyết định hành chính", "Công văn giải thích", "Án lệ tham chiếu", "Luật Phá sản", "Luật Cạnh tranh", "Luật BHXH"] as cap}
            <div class="flex items-center gap-6 px-10 py-5 border-r border-[#0F2044]/[0.06] shrink-0">
              <span class="w-1.5 h-1.5 rounded-full bg-[#0F2044]/20 shrink-0" />
              <span class="text-sm text-[#0F2044]/30 whitespace-nowrap tracking-wide font-sans">{cap}</span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  </section>

  <!-- ── CTA / FOOTER ── -->
  <section id="contact" class="relative py-32 px-6 md:px-12 lg:px-20 border-t border-[#0F2044]/[0.07] overflow-hidden">
    <!-- Navy bg panel -->
    <div class="absolute inset-0 pointer-events-none bg-[linear-gradient(to_bottom,transparent_0%,rgba(15,32,68,0.04)_100%)]" />

    <div class="relative z-10 max-w-3xl mx-auto text-center">
      <div class="mb-6">
        <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] tracking-widest font-sans text-[#C9A227] bg-[#C9A227]/10 border border-[#C9A227]/20">BẮT ĐẦU NGAY</span>
      </div>
      <h2 class="text-4xl md:text-5xl lg:text-6xl font-light tracking-tight leading-[1.05] mb-6 text-[#0F2044] font-sans">
        Đưa nghiên cứu pháp lý<br />lên một tiêu chuẩn mới.
      </h2>
      <p class="text-base text-[#0F2044]/50 leading-relaxed mb-10 max-w-xl mx-auto">
        Khám phá cách AI và GraphRAG giúp bạn tiếp cận hệ thống pháp luật Việt Nam nhanh hơn, chính xác hơn và minh bạch hơn.
      </p>

      {#if !submitted}
        <form
          on:submit|preventDefault={() => { if (email) submitted = true; }}
          class="flex flex-col sm:flex-row gap-2 max-w-md mx-auto mb-6"
        >
          <input
            type="email"
            placeholder="email@congty.vn"
            bind:value={email}
            required
            class="flex-1 bg-white border border-[#0F2044]/10 rounded-xl px-4 py-3 text-sm text-[#0F2044] placeholder:text-[#0F2044]/30 focus:outline-none focus:border-[#0F2044]/30 transition-colors"
          />
          <a
            href={tryNowLink}
            class="px-8 py-3 bg-[#0F2044] text-white text-sm rounded-xl hover:bg-[#1A3260] transition-colors tracking-wide font-medium flex items-center justify-center"
          >
            DÙNG THỬ
          </a>
        </form>
      {:else}
        <div class="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-[#C9A227]/20 bg-[#C9A227]/5 text-[#C9A227] text-sm mb-6">
          <div class="w-1.5 h-1.5 rounded-full bg-[#C9A227]" />
          Chúng tôi sẽ liên hệ với bạn sớm nhất.
        </div>
      {/if}

      <div class="mt-4">
        <a href="#contact" class="inline-flex items-center gap-2 text-sm text-[#0F2044]/50 hover:text-[#0F2044] transition-colors font-medium">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.6a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 3h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
          Liên hệ chuyên gia
        </a>
      </div>
    </div>
  </section>

  <!-- ── FOOTER ── -->
  <footer class="py-10 px-6 md:px-12 lg:px-20 border-t border-[#0F2044]/[0.07]">
    <div class="max-w-6xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
      <span class="font-sans text-sm font-semibold text-[#0F2044]">
        VietLegal<span class="text-[#C9A227]">GraphRAG</span>
      </span>

      <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
        {#each [
          { label: "Giải pháp",  href: "#solution" },
          { label: "Công nghệ", href: "#technology" },
          { label: "Tính năng", href: "#features" },
          { label: "Đối tượng", href: "#audience" },
          { label: "Liên hệ",   href: "#contact" }
        ] as l}
          <a href={l.href} class="text-xs text-[#0F2044]/40 hover:text-[#0F2044]/80 transition-colors tracking-wide font-sans">{l.label}</a>
        {/each}
      </div>

      <div class="flex items-center gap-6">
        {#each [
          { label: "Chính sách bảo mật", href: "#" },
          { label: "Điều khoản sử dụng", href: "#" },
          { label: "Tài liệu",            href: "#" }
        ] as l}
          <a href={l.href} class="text-xs text-[#0F2044]/25 hover:text-[#0F2044]/55 transition-colors font-sans">{l.label}</a>
        {/each}
      </div>
    </div>
    <div class="max-w-6xl mx-auto mt-8 pt-6 border-t border-[#0F2044]/[0.05]">
      <span class="text-xs text-[#0F2044]/20 font-sans">© 2026 VietLegalGraphRAG. Bảo lưu mọi quyền.</span>
    </div>
  </footer>
</div>
