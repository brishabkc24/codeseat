import { python } from "@codemirror/lang-python";
import { HighlightStyle, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo, useRef } from "react";

// Every colour here is a token from the stylesheet, so the editor follows the theme.
const surface = EditorView.theme(
  {
    "&": {
      height: "100%",
      backgroundColor: "var(--color-paper)",
      color: "var(--color-ink)",
      fontSize: "var(--text-code)",
    },
    "&.cm-focused": { outline: "1px solid var(--color-focus)", outlineOffset: "-1px" },
    ".cm-scroller": { fontFamily: "var(--font-outlier)", lineHeight: "1.6" },
    ".cm-content": { caretColor: "var(--color-accent)", padding: "var(--space-sm) 0" },
    ".cm-line": { padding: "0 var(--space-md) 0 var(--space-sm)" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--color-accent)" },
    ".cm-gutters": {
      backgroundColor: "var(--color-paper)",
      color: "var(--color-muted-2)",
      border: "none",
      borderRight: "1px solid var(--color-rule-2)",
    },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 var(--space-sm) 0 var(--space-md)" },
    ".cm-activeLine": { backgroundColor: "var(--color-paper-2)" },
    ".cm-activeLineGutter": { backgroundColor: "var(--color-paper-2)", color: "var(--color-ink-2)" },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground": {
      backgroundColor: "color-mix(in oklab, var(--color-accent) 30%, transparent)",
    },
    ".cm-matchingBracket, &.cm-focused .cm-matchingBracket": {
      backgroundColor: "transparent",
      outline: "1px solid var(--color-muted-2)",
    },
    ".cm-placeholder": { color: "var(--color-muted)" },
    ".cm-tooltip": {
      backgroundColor: "var(--color-paper-2)",
      border: "1px solid var(--color-rule)",
      color: "var(--color-ink)",
    },
    ".cm-tooltip-autocomplete ul li[aria-selected]": {
      backgroundColor: "var(--color-paper-3)",
      color: "var(--color-ink)",
    },
  },
  { dark: true },
);

const syntax = syntaxHighlighting(
  HighlightStyle.define([
    { tag: [tags.keyword, tags.operatorKeyword, tags.definitionKeyword], color: "var(--syn-keyword)" },
    { tag: [tags.string, tags.special(tags.string)], color: "var(--syn-string)" },
    { tag: [tags.number, tags.bool, tags.null], color: "var(--syn-number)" },
    { tag: [tags.comment, tags.lineComment], color: "var(--syn-comment)" },
    { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--color-ink)" },
    { tag: [tags.variableName, tags.propertyName], color: "var(--color-ink-2)" },
    { tag: [tags.operator, tags.punctuation, tags.bracket], color: "var(--color-muted)" },
  ]),
);

type Props = {
  value: string;
  /** Read by screen readers in place of a visible label. */
  label: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  /** Called on Ctrl+Enter (Cmd+Enter on a Mac). */
  onRun?: () => void;
};

export function CodeEditor({ value, label, onChange, readOnly = false, placeholder, onRun }: Props) {
  const runRef = useRef(onRun);
  runRef.current = onRun;

  const extensions = useMemo(
    () => [
      python(),
      indentUnit.of("    "),
      syntax,
      EditorView.contentAttributes.of({ "aria-label": label }),
      Prec.highest(
        keymap.of([
          {
            key: "Mod-Enter",
            run: () => {
              runRef.current?.();
              return true;
            },
          },
        ]),
      ),
    ],
    [label],
  );

  return (
    <CodeMirror
      className="editor"
      value={value}
      height="100%"
      theme={surface}
      extensions={extensions}
      onChange={onChange}
      readOnly={readOnly}
      editable={!readOnly}
      placeholder={placeholder}
      basicSetup={{
        foldGutter: false,
        highlightActiveLine: !readOnly,
        highlightActiveLineGutter: !readOnly,
        autocompletion: !readOnly,
      }}
    />
  );
}
