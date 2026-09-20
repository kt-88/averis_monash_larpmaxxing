export type Seg = { text: string; diff: boolean };

/**
 * Word-level comparison of two strings. Words that are not part of the longest run the two share are flagged,
 * so a reviewer sees exactly what differs ("MOMBASA" vs "TUTICORIN") instead of hunting for it.
 */
export function diffWords(a: string, b: string): { left: Seg[]; right: Seg[] } {
  const x = a.split(/\s+/).filter(Boolean);
  const y = b.split(/\s+/).filter(Boolean);
  const n = x.length, m = y.length;

  // t[i][j] = length of the longest common word run of x[i..] and y[j..]
  const t: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      t[i][j] = x[i] === y[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
    }
  }

  const left: Seg[] = [], right: Seg[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      left.push({ text: x[i], diff: false });
      right.push({ text: y[j], diff: false });
      i++; j++;
    } else if (t[i + 1][j] >= t[i][j + 1]) {
      left.push({ text: x[i++], diff: true });
    } else {
      right.push({ text: y[j++], diff: true });
    }
  }
  while (i < n) left.push({ text: x[i++], diff: true });
  while (j < m) right.push({ text: y[j++], diff: true });
  return { left, right };
}
