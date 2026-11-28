// The brush's result on a skin, live: the pictures' own layers (model_improve.skin_pictures: one per view, its colour
// and its weight as alpha) mixed as the projection mixes them - k = (prio x w)^sharp, the colour the k-weighted mean,
// the alpha 1.5 x the largest weight - with the strokes: «only this view» lowers the other views' weights (by the
// stroke's soft strength), the stamp takes the mix at the pixel that far away. Written into the picture's own canvas
// where the pins read it (q + D(q)), so it shows bent with the picture; pixels left unpainted get the picture back.
// «Tone from here»: that colour with the picture's own fine detail (the picture minus its blur), as the projection.
import * as THREE from 'three';

export const VCODE: Record<string, number> = { front: 0, back: 1, left: 2, right: 3 };
export interface BrushStroke { kind: 'only' | 'clone' | 'tone'; view?: string; off?: [number, number]; rgb?: [number, number, number];
  c: [number, number, number][] }
type Field = (x: number, y: number) => [number, number];

const loadImage = (url: string) => new Promise<HTMLImageElement>((ok, bad) => {
  const im = new Image();
  im.onload = () => ok(im);
  im.onerror = () => bad(new Error('image ' + url));
  im.src = url;
});
const pixels = (im: HTMLImageElement, W: number, H: number, blur = 0) => {
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const x = c.getContext('2d', { willReadFrequently: true })!;
  if (blur) x.filter = `blur(${blur}px)`;
  x.drawImage(im, 0, 0, W, H);
  return x.getImageData(0, 0, W, H);
};

export class BrushPreview {
  readonly tex: THREE.CanvasTexture;
  private ctx: CanvasRenderingContext2D;
  private img: ImageData;
  private base: Uint8ClampedArray;
  private only: Int8Array;
  private str: Float32Array;
  private off: Float32Array;   // (the stamp's offset per pixel, x and y; NaN: none)
  private tone: Float32Array;   // («tone from here»: the colour per pixel, NaN none; its strength)
  private toneS: Float32Array;
  private low: Uint8ClampedArray;   // (the picture blurred: its detail = the picture minus this)
  private applied: BrushStroke[] = [];
  private lastD: Field | null = null;

  private constructor(private W: number, private H: number, picture: ImageData, low: ImageData,
    private layers: { code: number; prio: number; px: Uint8ClampedArray }[], private sharp: number, private wrap: boolean) {
    const c = document.createElement('canvas');
    c.width = W; c.height = H;
    this.ctx = c.getContext('2d', { willReadFrequently: true })!;
    this.img = picture;
    this.base = new Uint8ClampedArray(picture.data);
    this.ctx.putImageData(this.img, 0, 0);
    this.tex = new THREE.CanvasTexture(c);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    this.only = new Int8Array(W * H).fill(-1);
    this.str = new Float32Array(W * H);
    this.off = new Float32Array(2 * W * H).fill(NaN);
    this.tone = new Float32Array(3 * W * H).fill(NaN);
    this.toneS = new Float32Array(W * H);
    this.low = low.data;
  }

  /** the colour shown round a point (the picture as now painted), weighted by how solid it is -> rgb or null */
  pick(x: number, y: number, r: number): [number, number, number] | null {
    const { W, H } = this, px = this.img.data;
    let sr = 0, sg = 0, sb = 0, sw = 0;
    const rr = Math.max(2, r);
    for (let j = Math.max(0, Math.floor(y - rr)); j < Math.min(H, Math.ceil(y + rr)); j++) {
      for (let i = Math.max(0, Math.floor(x - rr)); i < Math.min(W, Math.ceil(x + rr)); i++) {
        if (Math.hypot(i + 0.5 - x, j + 0.5 - y) > rr) continue;
        const o = 4 * (j * W + i), w = px[o + 3] / 255;
        sr += px[o] * w; sg += px[o + 1] * w; sb += px[o + 2] * w; sw += w;
      }
    }
    return sw > 0.5 ? [Math.round(sr / sw), Math.round(sg / sw), Math.round(sb / sw)] : null;
  }

  static async load(picture: string, layers: Record<string, string>, W: number, H: number, prio: Record<string, number>,
    sharp: number, wrap: boolean) {
    const names = Object.keys(layers);
    const ims = await Promise.all([loadImage(picture), ...names.map((v) => loadImage(layers[v]))]);
    const ls = names.map((v, i) => ({ code: VCODE[v] ?? -9, prio: prio[v] ?? 1, px: pixels(ims[i + 1], W, H).data }));
    return new BrushPreview(W, H, pixels(ims[0], W, H), pixels(ims[0], W, H, Math.max(4, Math.round(0.006 * W))), ls, sharp, wrap);
  }

  /** the strokes now (and the pins' field D): only what changed is mixed again -> true when the canvas changed */
  update(strokes: BrushStroke[], D: Field) {
    const box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    const grow = (x: number, y: number, r: number) => {
      box.x0 = Math.min(box.x0, x - r); box.y0 = Math.min(box.y0, y - r);
      box.x1 = Math.max(box.x1, x + r); box.y1 = Math.max(box.y1, y + r);
    };
    const old = this.applied;
    const sameKind = (a: BrushStroke, b: BrushStroke) => a.kind === b.kind && a.view === b.view
      && (a.off?.[0] ?? 0) === (b.off?.[0] ?? 0) && (a.off?.[1] ?? 0) === (b.off?.[1] ?? 0) && String(a.rgb) === String(b.rgb);
    const extends_ = D === this.lastD && strokes.length >= old.length
      && old.every((s, i) => sameKind(s, strokes[i]) && strokes[i].c.length >= s.c.length && (!s.c.length || strokes[i].c[0] === s.c[0]));
    if (extends_) {   // (circles added: only those)
      strokes.forEach((s, i) => {
        for (const [x, y, r] of s.c.slice(i < old.length ? old[i].c.length : 0)) { this.dab(s, x, y, r); grow(x, y, r); }
      });
    } else {   // (erased, undone, cleared, other pins: all again, where the old strokes were too)
      this.only.fill(-1); this.str.fill(0); this.off.fill(NaN); this.tone.fill(NaN); this.toneS.fill(0);
      for (const s of old) for (const [x, y, r] of s.c) grow(x, y, r);
      for (const s of strokes) for (const [x, y, r] of s.c) { this.dab(s, x, y, r); grow(x, y, r); }
      if (D !== this.lastD && old.length + strokes.length) { box.x0 = 0; box.y0 = 0; box.x1 = this.W; box.y1 = this.H; }
    }
    this.applied = strokes;
    this.lastD = D;
    if (box.x1 < box.x0) return false;
    this.paint(Math.max(0, Math.floor(box.x0)), Math.max(0, Math.floor(box.y0)),
      Math.min(this.W, Math.ceil(box.x1) + 1), Math.min(this.H, Math.ceil(box.y1) + 1), D);
    return true;
  }

  /** one circle into the masks (as model_improve.brush_masks: a later one wins; the same view's strength: the larger) */
  private dab(s: BrushStroke, x: number, y: number, r: number) {
    const { W, H } = this;
    const code = s.kind === 'only' ? VCODE[s.view || ''] ?? -1 : -1;
    if (s.kind === 'only' && code < 0) return;
    if (s.kind === 'tone' && !s.rgb) return;
    for (let j = Math.max(0, Math.floor(y - r)); j < Math.min(H, Math.ceil(y + r) + 1); j++) {
      for (let i = Math.max(0, Math.floor(x - r)); i < Math.min(W, Math.ceil(x + r) + 1); i++) {
        const d = Math.hypot(i + 0.5 - x, j + 0.5 - y);
        if (d > r) continue;
        const k = j * W + i;
        if (s.kind === 'tone') {   // (its own layer: the pictures' choice and the stamp stay)
          const st = Math.min(1, Math.max(0, (r - d) / Math.max(r / 3, 1e-6)));
          const same = this.tone[3 * k] === s.rgb![0] && this.tone[3 * k + 1] === s.rgb![1] && this.tone[3 * k + 2] === s.rgb![2];
          this.toneS[k] = same ? Math.max(this.toneS[k], st) : st;
          this.tone[3 * k] = s.rgb![0]; this.tone[3 * k + 1] = s.rgb![1]; this.tone[3 * k + 2] = s.rgb![2];
        } else if (s.kind === 'only') {
          const st = Math.min(1, Math.max(0, (r - d) / Math.max(r / 3, 1e-6)));
          this.str[k] = this.only[k] === code ? Math.max(this.str[k], st) : st;
          this.only[k] = code;
          this.off[2 * k] = NaN; this.off[2 * k + 1] = NaN;
        } else {
          this.off[2 * k] = s.off![0]; this.off[2 * k + 1] = s.off![1];
          this.only[k] = -1; this.str[k] = 0;
        }
      }
    }
  }

  /** the mixed colour at a picture pixel, the views but «only» lowered -> rgba into out at o */
  private mix(k: number, onlyCode: number, strength: number, out: Uint8ClampedArray, o: number) {
    let r = 0, g = 0, b = 0, ks = 0, cover = 0;
    for (const L of this.layers) {
      const i = 4 * k;
      let w = L.px[i + 3] / 255;
      if (onlyCode >= 0 && L.code !== onlyCode) w *= 1 - strength;
      if (w <= 0) continue;
      cover = Math.max(cover, w);
      const kk = Math.pow(L.prio * w, this.sharp);
      r += L.px[i] * kk; g += L.px[i + 1] * kk; b += L.px[i + 2] * kk; ks += kk;
    }
    if (ks > 0) { out[o] = r / ks; out[o + 1] = g / ks; out[o + 2] = b / ks; } else { out[o] = 0; out[o + 1] = 0; out[o + 2] = 0; }
    out[o + 3] = Math.min(1, cover * 1.5) * 255;
  }

  private paint(x0: number, y0: number, x1: number, y1: number, D: Field) {
    const { W, H } = this;
    const px = this.img.data;
    let dx0 = Infinity, dy0 = Infinity, dx1 = -Infinity, dy1 = -Infinity;
    for (let j = y0; j < y1; j++) {
      for (let i = x0; i < x1; i++) {
        const k = j * W + i;
        const [ex, ey] = D(i + 0.5, j + 0.5);   // (the picture pixel the pins read for this skin pixel)
        const pi = Math.round(i + ex), pj = Math.round(j + ey);
        if (pi < 0 || pj < 0 || pi >= W || pj >= H) continue;
        const p = pj * W + pi, o = 4 * p;
        const ox = this.off[2 * k];
        if (!Number.isNaN(ox)) {   // (the stamp: the mix at the pixel that far away)
          let si = Math.floor(i + ox), sj = Math.floor(j + this.off[2 * k + 1]);
          si = this.wrap ? ((si % W) + W) % W : Math.min(W - 1, Math.max(0, si));
          sj = Math.min(H - 1, Math.max(0, sj));
          this.mix(sj * W + si, -1, 0, px, o);
        } else if (this.only[k] >= 0) {
          this.mix(p, this.only[k], this.str[k], px, o);
        } else {
          px[o] = this.base[o]; px[o + 1] = this.base[o + 1]; px[o + 2] = this.base[o + 2]; px[o + 3] = this.base[o + 3];
        }
        const ts = this.toneS[k];
        if (ts > 0) {   // (the tone with the picture's detail; solid even where no picture sees: the texture gets it)
          for (let c = 0; c < 3; c++) {
            const v = this.tone[3 * k + c] + (this.base[o + c] - this.low[o + c]) * (this.base[o + 3] / 255);
            px[o + c] = px[o + c] * (1 - ts) + v * ts;
          }
          px[o + 3] = Math.max(px[o + 3], ts * 255);
        }
        dx0 = Math.min(dx0, pi); dy0 = Math.min(dy0, pj); dx1 = Math.max(dx1, pi); dy1 = Math.max(dy1, pj);
      }
    }
    if (dx1 < dx0) return;
    this.ctx.putImageData(this.img, 0, 0, dx0, dy0, dx1 - dx0 + 1, dy1 - dy0 + 1);
    this.tex.needsUpdate = true;
  }
}
