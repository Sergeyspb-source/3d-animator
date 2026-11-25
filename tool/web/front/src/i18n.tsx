// Texts by key from tool/lang/<code>.json (the Gradio app's catalog; the web UI's own keys are web.*).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { get, post } from './api';

type T = (key: string, ...args: unknown[]) => string;
interface I18n { lang: string; langs: Record<string, string>; t: T; setLang: (code: string) => void }
const Ctx = createContext<I18n>({ lang: 'ru', langs: {}, t: (k) => k, setLang: () => {} });

// Python's str.format as the catalog uses it: {} in turn, {0} by place, {:.1f} with a precision; {{ }} literal
export function format(text: string, args: unknown[]): string {
  let next = 0;
  return text.replace(/\{\{|\}\}|\{(\d*)(?::([^}]*))?\}/g, (m, idx: string | undefined, spec: string | undefined) => {
    if (m === '{{') return '{';
    if (m === '}}') return '}';
    const v = args[idx ? Number(idx) : next++];
    if (v === undefined) return m;
    const f = spec && /^\.(\d+)f$/.exec(spec);
    if (f && typeof v === 'number') return v.toFixed(Number(f[1]));
    return String(v);
  });
}

export function I18nProvider({ initial, langs, children }: { initial: string; langs: Record<string, string>; children: ReactNode }) {
  const [lang, setLangState] = useState(initial);
  const [text, setText] = useState<Record<string, string>>({});
  useEffect(() => { get<{ text: Record<string, string> }>(`/api/i18n?lang=${lang}`).then((r) => setText(r.text)); }, [lang]);
  const t = useCallback<T>((key, ...args) => { const s = text[key] ?? key; return args.length ? format(s, args) : s; }, [text]);
  const setLang = useCallback((code: string) => {
    setLangState(code);
    document.documentElement.lang = code;
    post('/api/lang', { lang: code }).catch(() => {});
  }, []);
  const value = useMemo(() => ({ lang, langs, t, setLang }), [lang, langs, t, setLang]);
  return <Ctx.Provider value={value}>{Object.keys(text).length ? children : null}</Ctx.Provider>;
}
export const useI18n = () => useContext(Ctx);
export const useT = () => useContext(Ctx).t;
// a Gradio text written in Markdown, shown as plain text (its **bold** and `code` marks dropped)
export const plain = (s: string) => s.replace(/\*\*|`/g, '');
