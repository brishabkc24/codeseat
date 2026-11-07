// Runs Python off the main thread, so a slow or endless program never freezes
// the page. The page talks to this worker with messages:
//
//   page -> worker   { type: "init", meta?, bytes? }   start Python (buffers allow input())
//                    { type: "run", id, source, stdin? } run a program; stdin, when given, is
//                                                      text whose lines answer input() in turn
//   worker -> page   { type: "ready" } | { type: "failed", message }
//                    { type: "output", chunks: [[stream, text], ...] }
//                    { type: "input" }                  the program is waiting for a line
//                    { type: "done", id, status }       status: ok | error | limit
//
// Stopping a program is done by the page: it terminates this worker and starts a new one.

import { loadPyodide } from "/pyodide/pyodide.mjs";

const MAX_OUTPUT = 200_000; // characters a single run may print
const FLUSH_CHARS = 8_192;
const FLUSH_MS = 40;

let runProgram = null;
let stdin = null; // { meta: Int32Array, bytes: Uint8Array } when input() is available
let script = null; // lines still to hand to input() during a run with stdin given

/** "3\n4\n" and "3\n4" are both two lines; "" is none. */
function toLines(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

let chunks = [];
let chunkChars = 0;
let lastFlush = 0;
let printed = 0;

function flush() {
  if (chunks.length > 0) {
    postMessage({ type: "output", chunks });
    chunks = [];
    chunkChars = 0;
  }
  lastFlush = performance.now();
}

// Python cannot yield to the browser while it runs, so output is batched here
// and sent whenever enough has piled up or enough time has passed.
const host = {
  write(stream, text) {
    printed += text.length;
    if (printed > MAX_OUTPUT) return false;
    const last = chunks[chunks.length - 1];
    if (last && last[0] === stream) last[1] += text;
    else chunks.push([stream, text]);
    chunkChars += text.length;
    if (chunkChars >= FLUSH_CHARS || performance.now() - lastFlush >= FLUSH_MS) flush();
    return true;
  },

  can_read() {
    return script !== null || stdin !== null;
  },

  // Answers from the given lines, or blocks this worker until the page hands over a line.
  read_line() {
    if (script !== null) return script.length > 0 ? script.shift() : null;
    flush();
    Atomics.store(stdin.meta, 0, 0);
    postMessage({ type: "input" });
    Atomics.wait(stdin.meta, 0, 0);
    if (Atomics.load(stdin.meta, 0) !== 1) return null;
    const length = Atomics.load(stdin.meta, 1);
    return new TextDecoder().decode(stdin.bytes.slice(0, length));
  },
};

const BOOTSTRAP = `
import builtins, linecache, sys, traceback
import codeseat_host


class _OutputLimit(BaseException):
    pass


class _Stream:
    encoding = "utf-8"

    def __init__(self, name):
        self.name = name

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError("write() argument must be str, not " + type(text).__name__)
        if text and not codeseat_host.write(self.name, text):
            raise _OutputLimit()
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return True

    def writable(self):
        return True


def _input(prompt=""):
    if prompt != "":
        sys.stdout.write(str(prompt))
    if not codeseat_host.can_read():
        raise RuntimeError("input() is not available in this browser. Open CodeSeat in a current Chrome, Edge or Firefox.")
    line = codeseat_host.read_line()
    if line is None:
        raise EOFError("EOF when reading a line")
    return line


def _codeseat_run(source):
    sys.stdout = _Stream("stdout")
    sys.stderr = _Stream("stderr")
    builtins.input = _input
    # Lets tracebacks quote the offending line of the student's program.
    linecache.cache["main.py"] = (len(source), None, source.splitlines(True), "main.py")
    scope = {"__name__": "__main__", "__builtins__": builtins}
    try:
        exec(compile(source, "main.py", "exec"), scope)
        return "ok"
    except _OutputLimit:
        return "limit"
    except SystemExit:
        return "ok"
    except BaseException as error:
        trace = error.__traceback__
        if trace is not None:
            trace = trace.tb_next  # hide this runner's own frame
        try:
            traceback.print_exception(type(error), error, trace)
        except _OutputLimit:
            return "limit"
        return "error"


_codeseat_run
`;

async function start(message) {
  if (message.meta && message.bytes) {
    stdin = { meta: new Int32Array(message.meta), bytes: new Uint8Array(message.bytes) };
  }
  try {
    const pyodide = await loadPyodide({ indexURL: "/pyodide/" });
    pyodide.registerJsModule("codeseat_host", host);
    runProgram = pyodide.runPython(BOOTSTRAP);
    postMessage({ type: "ready" });
  } catch (error) {
    postMessage({ type: "failed", message: String(error) });
  }
}

function run(message) {
  printed = 0;
  lastFlush = performance.now();
  script = typeof message.stdin === "string" ? toLines(message.stdin) : null;
  let status;
  try {
    status = runProgram(message.source);
  } catch (error) {
    // Python itself broke (for example it ran out of memory), not the student's code.
    chunks.push(["stderr", `${error}\n`]);
    status = "error";
  }
  flush();
  postMessage({ type: "done", id: message.id, status });
}

self.onmessage = (event) => {
  const message = event.data;
  if (message.type === "init") start(message);
  else if (message.type === "run" && runProgram) run(message);
};
