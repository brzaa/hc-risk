const STORAGE_KEY = "sicp-python-lab-progress-v1";

const lessons = [
  {
    id: "lesson-1",
    title: "Compound Expressions",
    tag: "01 / Expressions",
    summary: "Start with the basic SICP habit: build larger processes from smaller expressions.",
    concept:
      "A procedure call is a nested expression tree. The important step is to read code by substitution: what does each call become?",
    prompt:
      "Define `square(x)` and `sum_of_squares(a, b)`. Then define `f(a)` so it returns the sum of squares of `a + 1` and `a * 2`.",
    reflection:
      "If you replaced each function call by its body step by step, would the process still make sense on paper?",
    starterCode: `def square(x):\n    # return x squared\n    pass\n\n\ndef sum_of_squares(a, b):\n    # use square twice\n    pass\n\n\ndef f(a):\n    # combine the expressions using sum_of_squares\n    pass\n`,
    hints: [
      "Use `return`, not `print`.",
      "`sum_of_squares(a, b)` should call `square(a)` and `square(b)`.",
      "For `f(a)`, the two inputs are `a + 1` and `a * 2`.",
    ],
    solution: `def square(x):\n    return x * x\n\n\ndef sum_of_squares(a, b):\n    return square(a) + square(b)\n\n\ndef f(a):\n    return sum_of_squares(a + 1, a * 2)\n`,
    tests: [
      ["square(5)", "25"],
      ["sum_of_squares(3, 4)", "25"],
      ["f(3)", "52"],
    ],
  },
  {
    id: "lesson-2",
    title: "Procedural Abstraction",
    tag: "02 / Abstraction",
    summary: "Use names to hide detail and make your program talk in ideas instead of raw operations.",
    concept:
      "Good procedures separate what is being computed from how it is computed. That is the first major payoff of abstraction.",
    prompt:
      "Write `average(x, y)` and `improve_guess(guess, x)` for Newton-style square root refinement. Then write `sqrt_step(x)` that starts from `1.0` and applies `improve_guess` once.",
    reflection:
      "Did naming a sub-step make the final function easier to read than one large arithmetic expression?",
    starterCode: `def average(x, y):\n    pass\n\n\ndef improve_guess(guess, x):\n    pass\n\n\ndef sqrt_step(x):\n    pass\n`,
    hints: [
      "The average of two values is their sum divided by two.",
      "Newton improvement for square roots is the average of `guess` and `x / guess`.",
      "`sqrt_step(x)` should call `improve_guess(1.0, x)`.",
    ],
    solution: `def average(x, y):\n    return (x + y) / 2\n\n\ndef improve_guess(guess, x):\n    return average(guess, x / guess)\n\n\ndef sqrt_step(x):\n    return improve_guess(1.0, x)\n`,
    tests: [
      ["average(10, 14)", "12.0"],
      ["round(improve_guess(1.0, 9), 5)", "5.0"],
      ["round(sqrt_step(9), 5)", "5.0"],
    ],
  },
  {
    id: "lesson-3",
    title: "Linear Recursion",
    tag: "03 / Recursion",
    summary: "This is where process matters. The same math can create a recursive or iterative shape.",
    concept:
      "A recursive definition is natural when a problem reduces cleanly to a smaller instance. The key is choosing the base case and the smaller step.",
    prompt:
      "Define `factorial(n)` recursively. Then define `sum_to(n)` recursively so it returns `1 + 2 + ... + n` with `sum_to(0) == 0`.",
    reflection:
      "When you read your function, can you clearly point to the base case and the smaller subproblem?",
    starterCode: `def factorial(n):\n    pass\n\n\ndef sum_to(n):\n    pass\n`,
    hints: [
      "For factorial, `0!` is `1`.",
      "A recursive factorial step is `n * factorial(n - 1)`.",
      "For `sum_to`, reduce to `n + sum_to(n - 1)`.",
    ],
    solution: `def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)\n\n\ndef sum_to(n):\n    if n == 0:\n        return 0\n    return n + sum_to(n - 1)\n`,
    tests: [
      ["factorial(5)", "120"],
      ["sum_to(5)", "15"],
      ["sum_to(0)", "0"],
    ],
  },
  {
    id: "lesson-4",
    title: "Higher-Order Procedures",
    tag: "04 / Higher Order",
    summary: "Procedures can consume procedures. That is one of the central SICP moves.",
    concept:
      "A higher-order function lets you capture a pattern once and vary the specific operation by passing another function into it.",
    prompt:
      "Write `apply_twice(fn, x)` so it applies `fn` two times. Then write `increment(n)` and show that `apply_twice(increment, 3)` becomes `5`.",
    reflection:
      "Does your function talk about the pattern of computation rather than one special case?",
    starterCode: `def apply_twice(fn, x):\n    pass\n\n\ndef increment(n):\n    pass\n`,
    hints: [
      "Calling `fn` once gives the intermediate value.",
      "Calling it twice means `fn(fn(x))`.",
      "`increment` just returns the input plus one.",
    ],
    solution: `def apply_twice(fn, x):\n    return fn(fn(x))\n\n\ndef increment(n):\n    return n + 1\n`,
    tests: [
      ["apply_twice(increment, 3)", "5"],
      ["apply_twice(lambda x: x * 2, 4)", "16"],
    ],
  },
  {
    id: "lesson-5",
    title: "Local State With Closures",
    tag: "05 / Closures",
    summary: "State is where a program starts to feel alive. Closures let a function remember information between calls.",
    concept:
      "An inner function can capture variables from its enclosing scope. That gives you a controlled pocket of state without global variables.",
    prompt:
      "Write `make_adder(n)` so it returns a function that adds `n` to its input. Then write `make_counter()` so each call to the returned function produces 1, 2, 3, ...",
    reflection:
      "Which values are local to the outer function, and which survive because the inner function closes over them?",
    starterCode: `def make_adder(n):\n    pass\n\n\ndef make_counter():\n    pass\n`,
    hints: [
      "`make_adder(n)` should return an inner function.",
      "Use `nonlocal` inside the counter closure.",
      "Initialize the counter state in the outer function, not at module level.",
    ],
    solution: `def make_adder(n):\n    def adder(x):\n        return x + n\n    return adder\n\n\ndef make_counter():\n    count = 0\n\n    def counter():\n        nonlocal count\n        count += 1\n        return count\n\n    return counter\n`,
    tests: [
      ["add3 = make_adder(3)\nadd3(10)", "13"],
      ["c = make_counter()\n[c(), c(), c()]", "[1, 2, 3]"],
    ],
  },
];

const state = {
  lessonIndex: 0,
  pyodide: null,
  pyodideReady: false,
  progress: loadProgress(),
  hintsVisible: false,
  antigravity: false,
};

const els = {};

document.addEventListener("DOMContentLoaded", async () => {
  cacheElements();
  bindEvents();
  renderLessonRail();
  renderLesson();
  updateProgress();
  loadPyodideRuntime();
});

function cacheElements() {
  [
    "lesson-list",
    "lesson-tag",
    "lesson-title",
    "lesson-summary",
    "lesson-concept",
    "lesson-prompt",
    "lesson-reflection",
    "code-editor",
    "console-output",
    "solution-output",
    "solution-panel",
    "progress-value",
    "runtime-status",
    "result-status",
    "result-run",
    "result-save",
    "hint-list",
    "gravity-toggle",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  document.getElementById("run-code").addEventListener("click", runCurrentLesson);
  document.getElementById("show-solution").addEventListener("click", () => {
    els["solution-panel"].open = true;
  });
  document.getElementById("solution-toggle").addEventListener("click", toggleHints);
  document.getElementById("reset-lesson").addEventListener("click", resetLesson);
  els["gravity-toggle"].addEventListener("click", toggleAntigravity);
  els["code-editor"].addEventListener("input", persistCurrentDraft);
}

function loadProgress() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveProgress() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.progress));
}

function getCurrentLesson() {
  return lessons[state.lessonIndex];
}

function getLessonProgress(id) {
  return state.progress[id] || {};
}

function renderLessonRail() {
  els["lesson-list"].innerHTML = "";
  lessons.forEach((lesson, index) => {
    const progress = getLessonProgress(lesson.id);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lesson-pill";
    if (index === state.lessonIndex) button.classList.add("is-active");
    if (progress.completed) button.classList.add("is-complete");
    button.innerHTML = `
      <span>${lesson.tag}</span>
      <strong>${lesson.title}</strong>
      <small>${progress.completed ? "complete" : "practice"}</small>
    `;
    button.addEventListener("click", () => {
      state.lessonIndex = index;
      renderLessonRail();
      renderLesson();
    });
    els["lesson-list"].append(button);
  });
}

function renderLesson() {
  const lesson = getCurrentLesson();
  const progress = getLessonProgress(lesson.id);

  els["lesson-tag"].textContent = lesson.tag;
  els["lesson-title"].textContent = lesson.title;
  els["lesson-summary"].textContent = lesson.summary;
  els["lesson-concept"].textContent = lesson.concept;
  els["lesson-prompt"].textContent = lesson.prompt;
  els["lesson-reflection"].textContent = lesson.reflection;
  els["code-editor"].value = progress.code || lesson.starterCode;
  els["solution-output"].textContent = lesson.solution;
  els["result-status"].textContent = progress.completed ? "Passed" : "Waiting";
  els["result-run"].textContent = progress.lastRun || "Not yet";
  els["result-save"].textContent = progress.code ? "Saved locally" : "Starter loaded";
  els["console-output"].textContent = progress.output || 'Press "Run Tests" to execute your code.';

  renderHints();
}

function renderHints() {
  const lesson = getCurrentLesson();
  els["hint-list"].innerHTML = "";
  lesson.hints.forEach((hint, index) => {
    const item = document.createElement("div");
    item.className = "hint-item";
    item.innerHTML = `<strong>Hint ${index + 1}</strong><span>${state.hintsVisible ? hint : "Hidden until hints are enabled."}</span>`;
    els["hint-list"].append(item);
  });
}

function updateProgress() {
  const completed = lessons.filter((lesson) => getLessonProgress(lesson.id).completed).length;
  els["progress-value"].textContent = `${completed} / ${lessons.length} complete`;
}

function persistCurrentDraft() {
  const lesson = getCurrentLesson();
  const entry = getLessonProgress(lesson.id);
  entry.code = els["code-editor"].value;
  entry.lastTouched = new Date().toLocaleString();
  state.progress[lesson.id] = entry;
  saveProgress();
  els["result-save"].textContent = "Saved locally";
}

function resetLesson() {
  const lesson = getCurrentLesson();
  const existing = getLessonProgress(lesson.id);
  state.progress[lesson.id] = {
    ...existing,
    code: lesson.starterCode,
    output: 'Lesson reset. Press "Run Tests" when ready.',
    completed: false,
  };
  saveProgress();
  renderLessonRail();
  renderLesson();
  updateProgress();
}

function toggleHints() {
  state.hintsVisible = !state.hintsVisible;
  document.getElementById("solution-toggle").textContent = state.hintsVisible ? "Hide hints" : "Show hints";
  renderHints();
}

function toggleAntigravity() {
  state.antigravity = !state.antigravity;
  document.body.classList.toggle("antigravity", state.antigravity);
  els["gravity-toggle"].textContent = state.antigravity ? "Antigravity On" : "Antigravity Off";
}

async function loadPyodideRuntime() {
  if (typeof loadPyodide !== "function") {
    els["runtime-status"].textContent = "Pyodide unavailable";
    els["console-output"].textContent =
      "The Python runtime could not load. If you are offline, the editor still saves drafts, but test execution needs the Pyodide CDN.";
    return;
  }

  try {
    els["runtime-status"].textContent = "Loading runtime...";
    state.pyodide = await loadPyodide();
    state.pyodideReady = true;
    els["runtime-status"].textContent = "Ready";
  } catch (error) {
    els["runtime-status"].textContent = "Load failed";
    els["console-output"].textContent = `Runtime failed to load:\n${String(error)}`;
  }
}

async function runCurrentLesson() {
  const lesson = getCurrentLesson();
  const code = els["code-editor"].value;
  const progress = getLessonProgress(lesson.id);

  progress.code = code;
  progress.lastRun = new Date().toLocaleTimeString();
  state.progress[lesson.id] = progress;
  saveProgress();
  els["result-run"].textContent = progress.lastRun;

  if (!state.pyodideReady) {
    els["result-status"].textContent = "Runtime unavailable";
    els["console-output"].textContent = "Pyodide is not ready yet. Wait for the runtime status to become Ready.";
    return;
  }

  els["result-status"].textContent = "Running";
  const harness = buildHarness(code, lesson.tests);

  try {
    const output = await state.pyodide.runPythonAsync(harness);
    const passed = !output.includes("FAIL") && !output.includes("ERROR");
    progress.output = output;
    progress.completed = passed;
    state.progress[lesson.id] = progress;
    saveProgress();

    els["console-output"].textContent = output;
    els["result-status"].textContent = passed ? "Passed" : "Keep going";
    renderLessonRail();
    updateProgress();
  } catch (error) {
    progress.output = `Python error:\n${String(error)}`;
    progress.completed = false;
    state.progress[lesson.id] = progress;
    saveProgress();
    els["console-output"].textContent = progress.output;
    els["result-status"].textContent = "Error";
    renderLessonRail();
    updateProgress();
  }
}

function buildHarness(userCode, tests) {
  const serializedTests = JSON.stringify(tests);
  return `
${userCode}

TESTS = ${serializedTests}

def evaluate_snippet(snippet, namespace):
    parts = snippet.strip().split("\\n")
    if len(parts) == 1:
        return eval(parts[0], namespace)
    setup = "\\n".join(parts[:-1])
    final_expression = parts[-1]
    exec(setup, namespace)
    return eval(final_expression, namespace)

def run_tests():
    lines = []
    namespace = globals()
    for expression, expected in TESTS:
        try:
            actual = evaluate_snippet(expression, namespace)
            actual_text = repr(actual)
            if actual_text == expected:
                lines.append(f"PASS | {expression} -> {actual_text}")
            else:
                lines.append(f"FAIL | {expression} -> {actual_text} (expected {expected})")
        except Exception as exc:
            lines.append(f"ERROR | {expression} -> {exc}")
    return "\\n".join(lines)

run_tests()
`;
}
