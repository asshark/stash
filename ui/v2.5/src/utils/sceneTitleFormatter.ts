/**
 * Total Commander Multi-Rename Tool–compatible placeholders for scene titles.
 * Reference: http://www.ghisler.ch/wiki/index.php?title=Multi-Rename_Tool
 *
 * Supported: [N…], [P…], [G…], [E…], digit-leading ranges on full basename+ext,
 * [C…], [YMD], [Y], [M], [D], [d], [t], [h], [m], [s], [U], [L], [F], [n], [[]], []].
 * Content plugins [=…] are not supported (placeholder is left unchanged).
 */

export type SceneTitleFormatOptions = {
  /** 0-based index of the scene in the current bulk selection (for [C] math). */
  sequenceIndex?: number;
  now?: Date;
};

type CaseMode = "n" | "U" | "L" | "F";

function normalizePathSeparators(filePath: string) {
  return filePath.replace(/\\/g, "/");
}

function splitFilePath(filePath: string) {
  const norm = normalizePathSeparators(filePath.trim());
  const lastSlash = norm.lastIndexOf("/");
  const dir = lastSlash >= 0 ? norm.slice(0, lastSlash) : "";
  const basenameWithExt =
    lastSlash >= 0 ? norm.slice(lastSlash + 1) : norm;
  const dotIdx = basenameWithExt.lastIndexOf(".");
  const hasExt = dotIdx > 0;
  const ext = hasExt ? basenameWithExt.slice(dotIdx + 1) : "";
  const baseNoExt = hasExt
    ? basenameWithExt.slice(0, dotIdx)
    : basenameWithExt;
  const parentSeg = dir ? dir.split("/").filter(Boolean).pop() ?? "" : "";
  const parentDir = dir.includes("/")
    ? dir.slice(0, dir.lastIndexOf("/"))
    : "";
  const grandparentSeg = parentDir
    ? parentDir.split("/").filter(Boolean).pop() ?? ""
    : "";
  return { baseNoExt, ext, basenameWithExt, parentSeg, grandparentSeg };
}

/** Total Commander [N…]-style range on a string (1-based indices, [N2,5] = length). */
export function applyTcNameRange(s: string, spec: string): string {
  if (!spec) {
    return s;
  }
  const L = s.length;

  const clamp = (v: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(v, hi));

  // [N2--5] from 2nd char to 5th-last (inclusive)
  const mDoubleDash = spec.match(/^(\d+)--(\d+)$/);
  if (mDoubleDash) {
    const n1 = parseInt(mDoubleDash[1], 10);
    const n2 = parseInt(mDoubleDash[2], 10);
    const start = clamp(n1 - 1, 0, L);
    const endExclusive = L - n2 + 1;
    if (start >= endExclusive || start >= L) {
      return "";
    }
    return s.slice(start, clamp(endExclusive, 0, L));
  }

  // [N2,5] — 5 characters starting at 2
  const mComma = spec.match(/^(\d+),(\d+)$/);
  if (mComma) {
    const n1 = parseInt(mComma[1], 10);
    const len = parseInt(mComma[2], 10);
    const start = clamp(n1 - 1, 0, L);
    return s.slice(start, clamp(start + len, 0, L));
  }

  // [N-8,5] — 5 chars starting at 8th from end
  const mNegComma = spec.match(/^-(\d+),(\d+)$/);
  if (mNegComma) {
    const fromEnd = parseInt(mNegComma[1], 10);
    const len = parseInt(mNegComma[2], 10);
    const start = clamp(L - fromEnd, 0, L);
    return s.slice(start, clamp(start + len, 0, L));
  }

  // [N-8-5] — 8th-last through 5th-last (inclusive)
  const mNegRange = spec.match(/^-(\d+)-(\d+)$/);
  if (mNegRange) {
    const n1 = parseInt(mNegRange[1], 10);
    const n2 = parseInt(mNegRange[2], 10);
    const start = clamp(L - n1, 0, L);
    const endExclusive = clamp(L - n2 + 1, 0, L);
    if (start >= endExclusive) {
      return "";
    }
    return s.slice(start, endExclusive);
  }

  // [N-5-] — 5th-last to end
  const mNegOpen = spec.match(/^-(\d+)-$/);
  if (mNegOpen) {
    const n = parseInt(mNegOpen[1], 10);
    const start = clamp(L - n, 0, L);
    return s.slice(start, L);
  }

  // [N2-] — from 2nd char to end
  const mOpen = spec.match(/^(\d+)-$/);
  if (mOpen) {
    const n1 = parseInt(mOpen[1], 10);
    const start = clamp(n1 - 1, 0, L);
    return s.slice(start, L);
  }

  // [N2-5] — chars 2–5 (1-based inclusive)
  const mRange = spec.match(/^(\d+)-(\d+)$/);
  if (mRange) {
    const n1 = parseInt(mRange[1], 10);
    const n2 = parseInt(mRange[2], 10);
    const start = clamp(n1 - 1, 0, L);
    const endExclusive = clamp(n2, 0, L);
    if (start >= endExclusive) {
      return "";
    }
    return s.slice(start, endExclusive);
  }

  return s;
}

function formatCounterValue(
  inner: string,
  sequenceIndex: number
): string | null {
  const i = sequenceIndex;

  const full = inner.match(/^(\d+)\+(\d+):(\d+)$/);
  if (full) {
    const start = parseInt(full[1], 10);
    const step = parseInt(full[2], 10);
    const width = parseInt(full[3], 10);
    const v = start + i * step;
    return v.toString().padStart(Math.max(width, 1), "0");
  }

  const startWidth = inner.match(/^(\d+):(\d+)$/);
  if (startWidth) {
    const start = parseInt(startWidth[1], 10);
    const width = parseInt(startWidth[2], 10);
    const v = start + i;
    return v.toString().padStart(Math.max(width, 1), "0");
  }

  const startStep = inner.match(/^(\d+)\+(\d+)$/);
  if (startStep) {
    const start = parseInt(startStep[1], 10);
    const step = parseInt(startStep[2], 10);
    return (start + i * step).toString();
  }

  const stepWidth = inner.match(/^\+(\d+):(\d+)$/);
  if (stepWidth) {
    const step = parseInt(stepWidth[1], 10);
    const width = parseInt(stepWidth[2], 10);
    const v = 1 + i * step;
    return v.toString().padStart(Math.max(width, 1), "0");
  }

  const stepOnly = inner.match(/^\+(\d+)$/);
  if (stepOnly) {
    const step = parseInt(stepOnly[1], 10);
    return (1 + i * step).toString();
  }

  const widthOnly = inner.match(/^:(\d+)$/);
  if (widthOnly) {
    const width = parseInt(widthOnly[1], 10);
    const v = i + 1;
    return v.toString().padStart(Math.max(width, 1), "0");
  }

  const startOnly = inner.match(/^(\d+)$/);
  if (startOnly) {
    const start = parseInt(startOnly[1], 10);
    return (start + i).toString();
  }

  if (inner === "") {
    return (i + 1).toString();
  }

  return null;
}

function formatDateD(now: Date) {
  try {
    return now.toLocaleDateString(undefined).replace(/\//g, "-");
  } catch {
    return formatYmd(now);
  }
}

function formatTimeT(now: Date) {
  try {
    return now
      .toLocaleTimeString(undefined, { hour12: false })
      .replace(/:/g, ".");
  } catch {
    const h = now.getHours().toString().padStart(2, "0");
    const m = now.getMinutes().toString().padStart(2, "0");
    const s = now.getSeconds().toString().padStart(2, "0");
    return `${h}.${m}.${s}`;
  }
}

function formatYmd(date: Date) {
  const year = date.getFullYear().toString();
  const month = (date.getMonth() + 1).toString().padStart(2, "0");
  const day = date.getDate().toString().padStart(2, "0");
  return `${year}${month}${day}`;
}

function isWordChar(ch: string) {
  return /[0-9a-zA-ZÀ-ÖØ-öø-ÿ]/.test(ch);
}

function resolvePlainToken(
  token: string,
  parts: ReturnType<typeof splitFilePath>,
  sequenceIndex: number,
  now: Date
): string | null {
  if (token === "YMD") {
    return formatYmd(now);
  }
  if (token === "Y") {
    return now.getFullYear().toString();
  }
  if (token === "M") {
    return (now.getMonth() + 1).toString().padStart(2, "0");
  }
  if (token === "D") {
    return now.getDate().toString().padStart(2, "0");
  }
  if (token === "d") {
    return formatDateD(now);
  }
  if (token === "t") {
    return formatTimeT(now);
  }
  if (token === "h") {
    return now.getHours().toString().padStart(2, "0");
  }
  if (token === "m") {
    return now.getMinutes().toString().padStart(2, "0");
  }
  if (token === "s") {
    return now.getSeconds().toString().padStart(2, "0");
  }

  if (token === "N") {
    return parts.baseNoExt;
  }
  if (token.startsWith("N")) {
    return applyTcNameRange(parts.baseNoExt, token.slice(1));
  }

  if (token === "P") {
    return parts.parentSeg;
  }
  if (token.startsWith("P")) {
    return applyTcNameRange(parts.parentSeg, token.slice(1));
  }

  if (token === "G") {
    return parts.grandparentSeg;
  }
  if (token.startsWith("G")) {
    return applyTcNameRange(parts.grandparentSeg, token.slice(1));
  }

  if (token === "E") {
    return parts.ext;
  }
  if (token.startsWith("E")) {
    return applyTcNameRange(parts.ext, token.slice(1));
  }

  if (token.startsWith("C")) {
    const inner = token.slice(1);
    const c = formatCounterValue(inner, sequenceIndex);
    if (c !== null) {
      return c;
    }
  }

  if (/^\d/.test(token)) {
    return applyTcNameRange(parts.basenameWithExt, token);
  }

  if (token.startsWith("=")) {
    return `[${token}]`;
  }

  return null;
}

/**
 * @param filePath Full filesystem path to the primary video file (used for [N], [P], [G], [E], [2-5]).
 */
export function renderSceneTitlePattern(
  template: string,
  filePath: string,
  options?: SceneTitleFormatOptions
) {
  const sequenceIndex = options?.sequenceIndex ?? 0;
  const now = options?.now ?? new Date();
  const parts = splitFilePath(filePath);

  let caseMode: CaseMode = "n";
  let fWordStart = true;
  let result = "";
  let i = 0;

  function emit(text: string) {
    if (caseMode === "n") {
      result += text;
      return;
    }
    if (caseMode === "U") {
      result += text.toLocaleUpperCase();
      return;
    }
    if (caseMode === "L") {
      result += text.toLocaleLowerCase();
      return;
    }
    for (const ch of text) {
      if (isWordChar(ch)) {
        result += fWordStart ? ch.toLocaleUpperCase() : ch.toLocaleLowerCase();
        fWordStart = false;
      } else {
        result += ch;
        fWordStart = true;
      }
    }
  }

  while (i < template.length) {
    if (template.startsWith("[[]", i)) {
      emit("[");
      i += 3;
      continue;
    }

    if (template.startsWith("[]]", i)) {
      emit("]");
      i += 3;
      continue;
    }

    if (template[i] === "[") {
      const end = template.indexOf("]", i + 1);
      if (end !== -1) {
        const token = template.slice(i + 1, end);

        if (token === "U") {
          caseMode = "U";
          i = end + 1;
          continue;
        }
        if (token === "L") {
          caseMode = "L";
          i = end + 1;
          continue;
        }
        if (token === "F") {
          caseMode = "F";
          fWordStart = true;
          i = end + 1;
          continue;
        }
        if (token === "n") {
          caseMode = "n";
          i = end + 1;
          continue;
        }

        const resolved = resolvePlainToken(token, parts, sequenceIndex, now);
        const piece =
          resolved !== null ? resolved : `[${token}]`;
        emit(piece);
        i = end + 1;
        continue;
      }
    }

    emit(template[i]);
    i += 1;
  }

  return result;
}

export function getFilenameWithoutExtension(filePath: string) {
  return splitFilePath(filePath).baseNoExt;
}

export function getSceneSourceFilename(scene: {
  files?: Array<{ path?: string | null }> | null;
}) {
  const primaryPath = scene.files?.[0]?.path;
  if (!primaryPath) {
    return "";
  }

  return getFilenameWithoutExtension(primaryPath);
}

export function getScenePrimaryFilePath(scene: {
  files?: Array<{ path?: string | null }> | null;
}) {
  return scene.files?.[0]?.path ?? "";
}
