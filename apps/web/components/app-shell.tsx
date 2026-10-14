"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navigation = [
  { href: "/", label: "Dashboard" },
  { href: "/news", label: "News" },
  { href: "/signals", label: "Signals" },
  { href: "/backtest", label: "Backtests" },
  { href: "/paper", label: "Paper Trading" },
  { href: "/risk", label: "Risk Ops" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="shell">
      <div className="shell__frame">
        <header className="shell__hero">
          <div className="shell__eyebrow">XAU Compass</div>
          <h1 className="shell__title">黄金新闻驱动研究与模拟交易系统</h1>
          <p className="shell__subtitle">
            汇总新闻分析、信号生成、回测验证、模拟执行、风险状态和运行监控，所有页面只消费既有
            REST 合约。
          </p>
          <nav className="shell__nav" aria-label="Primary">
            {navigation.map((item) => {
              const isActive = item.href === "/" ? pathname === item.href : pathname.startsWith(item.href);
              return (
                <Link key={item.href} href={item.href} className="shell__nav-link" data-active={isActive}>
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>
        <main className="shell__main">{children}</main>
      </div>
    </div>
  );
}
