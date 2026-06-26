/**
 * Telegram WebApp 封装（T7）。
 *
 * 直接用 Telegram 容器注入的全局 `window.Telegram.WebApp`（由 index.html 引入
 * telegram-web-app.js 提供），不依赖 @twa-dev/sdk —— 零 npm 依赖。
 *
 * 取已签名的 initData 作为后端验签输入；非 Telegram 环境（本地浏览器）initData
 * 为空串，调用方据此降级（保留 mock 角色切换器）。
 */

interface TgWebApp {
  initData: string;
  ready: () => void;
  expand?: () => void;
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string>;
}

function tg(): TgWebApp | null {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } })?.Telegram?.WebApp ?? null;
}

let _ready = false;

/** 通知 Telegram 客户端 WebApp 已就绪并展开。多次调用安全。 */
export function tgReady(): void {
  if (_ready) return;
  try {
    const w = tg();
    w?.ready();
    w?.expand?.();
    _ready = true;
  } catch {
    /* 非 Telegram 环境：忽略 */
  }
}

/** 已签名的 initData；非 Telegram 环境返回空串。 */
export function getInitData(): string {
  try {
    return tg()?.initData || "";
  } catch {
    return "";
  }
}

/** 是否运行在 Telegram 容器内（有可用 initData）。 */
export function isInTelegram(): boolean {
  return getInitData().length > 0;
}
