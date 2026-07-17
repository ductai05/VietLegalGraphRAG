import React from "react"
import type { Metadata } from 'next'
import { Inter, Lora, Geist_Mono } from 'next/font/google'
import { Courier_Prime } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import './globals.css'

const _inter = Inter({ subsets: ["latin", "vietnamese"] });
const _lora = Lora({ subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const _geistMono = Geist_Mono({ subsets: ["latin"] });
const _courierPrime = Courier_Prime({ weight: ["400", "700"], subsets: ["latin"] });

export const metadata: Metadata = {
  title: 'VietLegalGraphRAG — AI Pháp Lý Thế Hệ Mới Cho Việt Nam',
  description: 'Trợ lý pháp lý AI đầu tiên tại Việt Nam ứng dụng công nghệ GraphRAG. Tìm kiếm, phân tích và kết nối hệ thống pháp luật Việt Nam với độ chính xác cao.',
  keywords: ['AI pháp lý', 'GraphRAG', 'luật Việt Nam', 'tra cứu pháp luật', 'trợ lý pháp lý AI', 'VietLegalGraphRAG'],
  authors: [{ name: 'VietLegalGraphRAG' }],
  openGraph: {
    title: 'VietLegalGraphRAG — AI Pháp Lý Thế Hệ Mới',
    description: 'Trợ lý pháp lý AI đầu tiên tại Việt Nam ứng dụng công nghệ GraphRAG.',
    type: 'website',
    siteName: 'VietLegalGraphRAG',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'VietLegalGraphRAG — AI Pháp Lý Thế Hệ Mới',
    description: 'Trợ lý pháp lý AI đầu tiên tại Việt Nam ứng dụng công nghệ GraphRAG.',
  },
  icons: {
    icon: '/icon.svg',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="vi" className="bg-background">
      <body className={`font-sans antialiased`}>
        {children}
        <Analytics />
      </body>
    </html>
  )
}
