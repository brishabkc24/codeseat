// Helpers for lesson steps. The server is the judge of a check (backend/app/rooms.py);
// these only explain its verdict, so they follow the same comparison rule.

import type { Step } from "./protocol";

/** Output as lines, the way it is compared: spaces at line ends and blank lines at the end do not count. */
export function tidyOutput(text: string): string[] {
  const lines = text
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd());
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/** The first line (counted from 1) where two outputs differ, or null when they match. */
export function firstDifference(expected: string, actual: string): number | null {
  const want = tidyOutput(expected);
  const got = tidyOutput(actual);
  const count = Math.max(want.length, got.length);
  for (let index = 0; index < count; index += 1) {
    if (want[index] !== got[index]) return index + 1;
  }
  return null;
}

export function stepNumber(steps: Step[], id: string): number {
  return steps.findIndex((step) => step.id === id) + 1;
}

/** Class names from pairs, skipping the ones switched off. */
export function classes(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
