/**
 * Telegram WebApp 封装（T7 + 体验打磨）。
 *
 * 直接用 Telegram 容器注入的全局 `window.Telegram.WebApp`（由 index.html 引入
 * telegram-web-app.js 提供），不依赖 @twa-dev/sdk —— 零 npm 依赖。
 *
 * 取已签名的 initData 作为后端验签输入；非 Telegram 环境（本地浏览器）initData
 * 为空串，调用方据此降级（保留手机框预览 + mock 角色切换器）。
 */

interface TgBackButton {
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
}

interface TgHaptic {
  impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
  notificationOccurred?: (type: "error" | "success" | "warning") => void;
  selectionChanged?: () => void;
}

interface TgWebApp {
  initData: string;
  ready: () => void;
  expand?: () => void;
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string>;
  BackButton?: TgBackButton;
  HapticFeedback?: TgHaptic;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
}

function tg(): TgWebApp | null {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } })?.Telegram?.WebApp ?? null;
}

let _ready = false;

/** 通知 Telegram 客户端 WebApp 已就绪并展开，并把头部/背景色对齐 App 暗色。多次调用安全。 */
export function tgReady(): void {
  if (_ready) return;
  try {
    const w = tg();
    w?.ready();
    w?.expand?.();
    // 与 App 容器底色一致，消除头部/底部割裂感。
    w?.setHeaderColor?.("#17212b");
    w?.setBackgroundColor?.("#17212b");
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

/** 显示 Telegram 原生返回键并绑定回调；返回解绑函数。非 Telegram 环境为 no-op。 */
export function showBackButton(onBack: () => void): () => void {
  const w = tg();
  const bb = w?.BackButton;
  if (!bb) return () => {};
  try {
    bb.onClick(onBack);
    bb.show();
  } catch {
    return () => {};
  }
  return () => {
    try {
      bb.hide();
      bb.offClick(onBack);
    } catch {
      /* ignore */
    }
  };
}

/** 轻触感反馈（如收藏）。非 Telegram 或不支持则静默。 */
export function hapticLight(): void {
  try {
    tg()?.HapticFeedback?.impactOccurred?.("light");
  } catch {
    /* ignore */
  }
}
